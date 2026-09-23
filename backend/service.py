"""One turn handler for HTTP text and the LiveKit worker.

Data-driven executor: `scenario.actions` from scenarios.json run in catalog order over
the session's in-memory copy of mock_backend.json. An action with `irreversible: true`
stops at a preview; the next explicit consent executes exactly the previewed parameters.
Nothing is committed to the session until the reply has been generated.
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
import re
from time import perf_counter
from uuid import uuid4

from .executor import ActionError, Executor

PRODUCTS = ("ogpo", "casco", "travel", "property", "accident", "dms")
IDENTIFIERS = ("phone", "iin", "policy_number", "claim_number", "vehicle_plate")
# actions.json error_handling: re-ask the identifier once, then offer another one or an operator.
REASK_ERRORS = {"not_found", "invalid_input"}
# Reversible but non-idempotent registrations: the same request in one session is registered once.
REGISTER_ONCE = {"create_complaint", "report_fraud", "create_callback", "send_sms"}
# Identifiers are assigned only on execute; a preview must not look like a finished operation.
ASSIGNED_ON_EXECUTE = ("policy_number", "claim_number", "ticket_id")


class RequestConflict(Exception):
    pass


@dataclass
class Session:
    id: str
    data: dict
    slots: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    active_scenario: str | None = None
    queued_scenarios: list = field(default_factory=list)
    low_confidence: int = 0
    client: dict | None = None
    pending: dict | None = None
    retries: dict = field(default_factory=dict)
    done: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def context(self):
        return {"active_scenario": self.active_scenario, "slots": self.slots,
                "queued_scenarios": self.queued_scenarios,
                "client": {"client_id": self.client["client_id"], "full_name": self.client["full_name"]} if self.client else None,
                "pending_confirmation": public_pending(self.pending),
                "history": self.history[-20:]}


def public_pending(pending):
    if not pending:
        return None
    return {k: pending[k] for k in ("confirmation_id", "action", "parameters", "summary")}


@dataclass
class Staged:
    """Per-turn working copy of the session; committed only after a successful reply."""
    data: dict
    slots: dict
    client: dict | None
    pending: dict | None
    retries: dict
    queued: list
    done: dict = field(default_factory=dict)
    active: str | None = None
    decision: str = "execute"
    actions: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    missing_alternatives: list | None = None
    handoff: dict | None = None
    warnings: list = field(default_factory=list)
    invalid: list = field(default_factory=list)
    confirmation_cancelled: bool = False
    low_confidence: int = 0


def valid_slot(spec, value):
    kind = spec["type"]
    if kind in {"string", "text", "date"} and not isinstance(value, str):
        return False
    if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if kind == "boolean" and not isinstance(value, bool):
        return False
    if kind == "list":
        # The pattern applies to each element (e.g. drivers_iin), not to str(list).
        if not isinstance(value, list) or not value:
            return False
        return all(isinstance(v, str) and (not spec.get("pattern") or re.fullmatch(spec["pattern"], v))
                   for v in value)
    if spec.get("pattern") and not re.fullmatch(spec["pattern"], str(value)):
        return False
    # Enum values in slots.json can be int (franchise, sum_insured) or str.
    if kind == "enum" and (isinstance(value, bool) or value not in spec["values"]):
        return False
    if kind == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    if "min" in spec and isinstance(value, (int, float)) and value < spec["min"]:
        return False
    if "max" in spec and isinstance(value, (int, float)) and value > spec["max"]:
        return False
    return True


def empty(value):
    return value in (None, "", [])


def product_of(scenario):
    return next((p for p in PRODUCTS if p in scenario["slug"]), None)


class TurnService:
    def __init__(self, catalog, router):
        self.catalog, self.router = catalog, router
        self.executor = Executor(catalog)
        self.sessions = {}

    def create_session(self):
        session = Session(id=str(uuid4()), data=self.catalog.new_mock_state())
        self.sessions[session.id] = session
        return session

    async def handle_turn(self, session_id, request):
        session = self.sessions[session_id]
        async with session.lock:
            if request.request_id in session.results:
                previous = session.results[request.request_id]
                if previous["transcript"] != request.text:
                    raise RequestConflict("request_id уже использован с другим текстом")
                return deepcopy(previous)
            start = perf_counter()
            route = await self.router.route(request.text, session.context())
            router_ms = (perf_counter() - start) * 1000
            t = self._decide(session, route, request.text)
            lang = route.response_language
            scenario = self.catalog.scenarios.get(t.active) if t.active else None
            context = {
                "decision": t.decision, "response_language": lang, "reason": route.reason,
                "client": t.client["full_name"] if t.client else None,
                "slots": t.slots, "missing_slots": t.missing,
                "slot_prompt": self.catalog.slots[t.missing[0]]["prompt"][lang] if t.missing else None,
                "missing_slot_alternatives": t.missing_alternatives,
                "actions": t.actions, "pending_confirmation": public_pending(t.pending),
                "confirmation_cancelled": t.confirmation_cancelled,
                "handoff": t.handoff, "queued_scenarios": t.queued,
                "scenario_responses": (scenario or {}).get("responses", {}).get(lang),
                "knowledge": self.catalog.knowledge,
            }
            reply_start = perf_counter()
            reply = await self.router.reply(request.text, context)
            result = {
                "session_id": session_id, "request_id": request.request_id, "turn_id": str(uuid4()),
                "turn": len(session.results) + 1, "mode": "live", "transcript": request.text,
                "language": route.language, "response_language": lang,
                "scenarios": [s.model_dump() for s in route.scenarios],
                "alternatives": [s.model_dump() for s in route.alternatives], "reason": route.reason,
                "is_continuation": route.is_continuation, "decision": t.decision,
                "active_scenario": t.active, "queued_scenarios": t.queued, "slots": t.slots,
                "missing_slots": t.missing, "actions": t.actions,
                "pending_confirmation": public_pending(t.pending),
                "handoff": t.handoff, "reply": reply, "audio_url": None,
                "latency_ms": {"stt": None, "triage": None, "router": router_ms,
                               "response": (perf_counter() - reply_start) * 1000,
                               "tts_first_audio": None, "total": None},
                "server_processing_ms": (perf_counter() - start) * 1000, "warnings": t.warnings,
            }
            session.data, session.slots, session.queued_scenarios = t.data, t.slots, t.queued
            session.client, session.pending, session.retries, session.done = t.client, t.pending, t.retries, t.done
            session.active_scenario = t.active if t.decision in {"collect_slots", "clarify", "confirm"} else None
            session.low_confidence = t.low_confidence
            session.history.extend([{"role": "user", "content": request.text}, {"role": "assistant", "content": reply}])
            session.results[request.request_id] = deepcopy(result)
            return result

    # ---- decision ---------------------------------------------------------------

    def _decide(self, session, route, text):
        t = Staged(data=deepcopy(session.data), slots=deepcopy(session.slots), client=deepcopy(session.client),
                   pending=deepcopy(session.pending), retries=dict(session.retries),
                   queued=list(session.queued_scenarios), done=dict(session.done))
        invalid = []
        for key, value in route.slots.items():
            if value is None:
                continue  # the model marks unknown slots as null; that is not an input error
            if valid_slot(self.catalog.slots[key], value):
                t.slots[key] = value
            else:
                invalid.append(key)
        t.invalid = invalid
        t.warnings = [{"stage": "slots", "code": "invalid_input", "message": f"Некорректный слот: {k}"} for k in invalid]
        primary = route.scenarios[0]
        scenario = self.catalog.scenarios.get(primary.scenario_id)
        t.low_confidence = session.low_confidence + 1 if primary.confidence < .45 else 0

        if primary.scenario_id == "SYS_GOODBYE":
            t.decision, t.pending = "goodbye", None
            return t
        if primary.scenario_id == "SYS_OUT_OF_SCOPE":
            t.decision = "out_of_scope"
            return t
        if t.low_confidence >= 2:
            t.decision, t.handoff = "handoff", {"queue": "operator_general", "summary": text}
            return t
        if primary.scenario_id == "SYS_UNCLEAR" or primary.confidence < .75:
            t.decision, t.active = "clarify", session.active_scenario
            return t

        same_topic = route.is_continuation or primary.scenario_id == session.active_scenario
        if t.pending:
            pending_topic = same_topic or primary.scenario_id == t.pending["scenario_id"]
            if route.confirmation == "yes" and pending_topic:
                self._execute_pending(t, text)
                self._continue_queue(t, text, route)
                return t
            if route.confirmation == "no" and pending_topic:
                t.pending, t.confirmation_cancelled = None, True
                t.decision, t.active = "clarify", scenario["scenario_id"]
                return t
            # Changed parameters or a new topic invalidate the old preview; it is rebuilt later.
            if not pending_topic:
                t.queued.append(t.pending["scenario_id"])
            t.pending = None

        for choice in route.scenarios[1:]:
            t.queued.append(choice.scenario_id)
        if session.active_scenario and not same_topic and session.active_scenario != primary.scenario_id:
            t.queued.append(session.active_scenario)
        self._run_scenario(t, scenario, text, route)
        self._continue_queue(t, text, route)
        return t

    def _continue_queue(self, t, text, route):
        t.queued = [q for q in dict.fromkeys(t.queued) if q != t.active and q in self.catalog.scenarios]
        # Multi-intent: once the primary scenario is finished, take the next queued one.
        if t.decision == "execute" and t.active is None and t.queued:
            nxt = self.catalog.scenarios[t.queued.pop(0)]
            missing = [n for n in nxt["slots"]["required"] if empty(t.slots.get(n))]
            if missing and not self._identified_for(t, nxt):
                t.active, t.decision, t.missing = nxt["scenario_id"], "collect_slots", missing
            else:
                self._run_scenario(t, nxt, text, route)
        t.queued = [q for q in dict.fromkeys(t.queued) if q != t.active]

    def _identified_for(self, t, scenario):
        return bool(t.client) and any(t.slots.get(k) for k in IDENTIFIERS)

    # ---- scenario pipeline ------------------------------------------------------

    def _run_scenario(self, t, scenario, text, route):
        sid = scenario["scenario_id"]
        t.active, t.missing, t.missing_alternatives = sid, [], None
        hand = scenario.get("handoff") or {}
        queue = hand.get("queue", "operator_general")
        product = product_of(scenario)
        names = scenario["actions"]
        needs_client = scenario["requires_identification"] or "find_client" in names

        # 1. Identification by phone/IIN as soon as the client gives one.
        if needs_client and not t.client and (t.slots.get("phone") or t.slots.get("iin")):
            if not self._act(t, "find_client", {k: t.slots.get(k) for k in ("phone", "iin")}, scenario):
                return
        # 2. Identifiers derivable from the client's data (one matching policy/claim).
        if t.client:
            self._autofill(t, scenario, product)

        # 3. Required slots; policy_number can be replaced by phone/IIN for identified scenarios.
        required = scenario["slots"]["required"]
        t.missing = [n for n in required if empty(t.slots.get(n))]
        if not t.missing and needs_client and not t.client and not any(t.slots.get(k) for k in IDENTIFIERS):
            t.missing = ["phone"]
        # A value the client just gave in a bad format is re-asked first (e.g. a misheard phone).
        retry = [n for n in t.invalid if n in required or (needs_client and n in IDENTIFIERS)]
        if retry:
            t.missing = retry[:1] + [n for n in t.missing if n != retry[0]]
        if t.missing:
            t.decision = "collect_slots"
            if "policy_number" in t.missing and needs_client and not t.client:
                t.missing_alternatives = ["phone", "iin"]
            return

        # 4. Actions in catalog order.
        params = {**t.slots, **self._client_facts(t), "queue": queue,
                  "product_type": t.slots.get("product_type") or product,
                  "topic": t.slots.get("topic") or scenario["slug"].replace("_", " ")}
        if empty(params.get("region")) and params.get("vehicle_plate"):
            # knowledge_base.products.ogpo.pricing.region_by_plate_code: the plate suffix names the region.
            codes = self.catalog.knowledge["products"]["ogpo"]["pricing"]["region_by_plate_code"]
            params["region"] = codes.get(str(params["vehicle_plate"])[-2:], codes["default"])
        results = {}
        for index, name in enumerate(names):
            if name == "find_client":
                continue
            if name == "transfer_to_operator":
                triggered = (hand.get("when") or "").startswith("always") or bool(route.handoff_reason) \
                    or t.slots.get("injured") is True \
                    or results.get("check_payment", {}).get("payment_status") == "charged_policy_not_issued"
                if not triggered:
                    continue
                self._act(t, name, params, scenario, results)
                t.decision, t.active = "handoff", None
                t.handoff = {"queue": queue, "summary": self._summary(t, text, route.handoff_reason or hand.get("when"))}
                return
            if name == "send_sms" and not params.get("phone"):
                continue
            if name == "get_bm_class" and params.get("iin") is None and params.get("drivers_iin"):
                # Quote scenarios list several drivers: one bonus-malus lookup per IIN.
                classes = {}
                for iin in params["drivers_iin"]:
                    try:
                        classes[iin] = self.executor.run(name, {"iin": iin}, t.data)["bm_class"]
                    except ActionError as exc:
                        t.actions.append({"name": name, "mode": "execute", "status": "error",
                                          "error": {"code": exc.code, "message": exc.message}})
                        self._on_error(t, name, exc, scenario, {"iin": iin})
                        return
                t.actions.append({"name": name, "mode": "execute", "status": "ok", "result": classes})
                continue
            unresolved = self._unresolved(name, params)
            if unresolved:
                slot = next((n for n in unresolved if n in self.catalog.slots), None)
                if slot:
                    t.decision, t.missing = "collect_slots", [slot]
                    return
                continue  # e.g. client_id without any identifier: nothing to look up
            if self.executor.is_irreversible(name):
                try:
                    preview = self.executor.run(name, deepcopy(params), deepcopy(t.data))
                except ActionError as exc:
                    t.actions.append({"name": name, "mode": "preview", "status": "error",
                                      "error": {"code": exc.code, "message": exc.message}})
                    self._on_error(t, name, exc, scenario, params)
                    return
                inputs = [alt for group in self.catalog.actions[name]["inputs"] for alt in group.split("|")]
                shown = {k: params[k] for k in inputs if params.get(k) is not None}
                shown.update({k: v for k, v in params.items() if k in self.catalog.slots and k not in shown})
                preview = {k: v for k, v in preview.items() if k not in ASSIGNED_ON_EXECUTE}
                t.actions.append({"name": name, "mode": "preview", "status": "ok", "result": preview})
                t.pending = {"confirmation_id": str(uuid4()), "action": name, "parameters": shown,
                             "summary": name + ": " + ", ".join(f"{k}={v}" for k, v in {**shown, **preview}.items()),
                             "scenario_id": sid, "params": deepcopy(params), "next_actions": names[index + 1:]}
                t.decision = "confirm"
                return
            if not self._act(t, name, params, scenario, results):
                return
            params.update({k: v for k, v in results.get(name, {}).items() if k not in ("simulated",)})
        t.decision, t.active = "execute", None

    def _execute_pending(self, t, text):
        pending, t.pending = t.pending, None
        scenario = self.catalog.scenarios[pending["scenario_id"]]
        params, results = pending["params"], {}
        if not self._act(t, pending["action"], params, scenario, results):
            return
        params.update(results[pending["action"]])
        for name in pending["next_actions"]:
            if name == "transfer_to_operator" and not ((scenario.get("handoff") or {}).get("when") or "").startswith("always"):
                continue
            if name == "send_sms" and not params.get("phone"):
                continue
            if self._unresolved(name, params):
                continue
            if not self._act(t, name, params, scenario, results):
                return
        t.decision, t.active = "execute", None

    # ---- helpers ------------------------------------------------------------------

    def _act(self, t, name, params, scenario, results=None):
        inputs = [alt for group in self.catalog.actions[name]["inputs"] for alt in group.split("|")]
        key = f"{scenario['scenario_id']}:{name}:" + repr(sorted((k, params.get(k)) for k in inputs))
        if name in REGISTER_ONCE and key in t.done:
            result = dict(t.done[key], already_registered=True)
        else:
            try:
                result = self.executor.run(name, params, t.data)
            except ActionError as exc:
                t.actions.append({"name": name, "mode": "execute", "status": "error",
                                  "error": {"code": exc.code, "message": exc.message}})
                if name == "kb_lookup":
                    return True  # the reply still has the whole knowledge base; nothing to re-ask
                self._on_error(t, name, exc, scenario, params)
                return False
            if name in REGISTER_ONCE:
                t.done[key] = result
        t.actions.append({"name": name, "mode": "execute", "status": "ok", "result": result})
        if results is not None:
            results[name] = result
        if result.get("client_id") and not t.client:
            record = next((c for c in t.data["clients"] if c["client_id"] == result["client_id"]), None)
            if record:
                t.client = deepcopy(record)
        return True

    def _on_error(self, t, name, exc, scenario, params):
        sid = scenario["scenario_id"]
        queue = (scenario.get("handoff") or {}).get("queue", "operator_general")
        if exc.code in REASK_ERRORS:
            inputs = [alt for group in self.catalog.actions[name]["inputs"] for alt in group.split("|")]
            used = [n for n in inputs if n in self.catalog.slots and params.get(n) is not None]
            key = f"{sid}:{name}"
            if used and t.retries.get(key, 0) < 1:
                t.retries[key] = 1
                for slot in used:
                    t.slots.pop(slot, None)
                t.decision, t.missing = "collect_slots", [used[0]]
                t.missing_alternatives = [n for n in inputs if n in self.catalog.slots and n != used[0]] or None
                return
        if exc.code in REASK_ERRORS or exc.code == "service_unavailable":
            t.decision, t.active = "handoff", None
            t.handoff = {"queue": queue, "summary": f"{name}: {exc.message}. Изменений данных не было."}
            return
        # policy_inactive / not_eligible / not_covered / no_availability / already_done:
        # explain the reason and offer the nearest valid option; the scenario is closed.
        t.decision, t.active = "execute", None

    def _unresolved(self, name, params):
        return [group for group in self.catalog.actions[name]["inputs"]
                if all(params.get(alt) is None for alt in group.split("|"))]

    def _client_facts(self, t):
        if not t.client:
            return {}
        facts = {"client_id": t.client["client_id"], "full_name": t.client["full_name"]}
        for key in ("phone", "email"):
            if t.client.get(key) and not t.slots.get(key):
                facts[key] = t.client[key]
        return facts

    def _autofill(self, t, scenario, product):
        inputs = {alt for name in scenario["actions"] for group in self.catalog.actions[name]["inputs"]
                  for alt in group.split("|")}
        wanted = set(scenario["slots"]["required"]) | set(scenario["slots"]["optional"]) | inputs
        if "policy_number" in wanted and empty(t.slots.get("policy_number")):
            policies = [p for p in self.executor.policies_for(t.data, t.client["client_id"], product)
                        if p.get("status") != "cancelled" and p["end_date"] >= self.catalog.as_of_date]
            if len(policies) == 1:
                t.slots["policy_number"] = policies[0]["policy_number"]
        if "city" in wanted and empty(t.slots.get("city")) and t.client.get("city") in self.catalog.slots["city"]["values"]:
            t.slots["city"] = t.client["city"]  # the client's registered city, as in the kit dialogs
        if "claim_number" in wanted and empty(t.slots.get("claim_number")):
            claims = [c for c in t.data["claims"] if c["client_id"] == t.client["client_id"]]
            if len(claims) == 1:
                t.slots["claim_number"] = claims[0]["claim_number"]

    def _summary(self, t, text, reason):
        parts = [text]
        if t.client:
            parts.append(f"клиент {t.client['full_name']} ({t.client['client_id']})")
        if reason:
            parts.append(f"причина: {reason}")
        done = [a["name"] for a in t.actions if a["status"] == "ok" and a["mode"] == "execute"]
        if done:
            parts.append("выполнено: " + ", ".join(done))
        return "; ".join(parts)
