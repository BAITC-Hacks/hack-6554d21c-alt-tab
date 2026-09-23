"""One turn handler for HTTP text and the LiveKit worker.

The first integration slice is deliberately read-only. Operations without an
executor return a visible simulated handoff, never a made-up success.
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
import re
from time import perf_counter
from uuid import uuid4


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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def context(self):
        return {"active_scenario": self.active_scenario, "slots": self.slots,
                "queued_scenarios": self.queued_scenarios, "history": self.history[-20:]}


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


class TurnService:
    def __init__(self, catalog, router):
        self.catalog, self.router = catalog, router
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
            # Stage state until every provider step has succeeded.
            slots = deepcopy(session.slots)
            invalid = []
            for key, value in route.slots.items():
                if value is None:
                    continue  # the model marks unknown slots as null; that is not an input error
                if valid_slot(self.catalog.slots[key], value):
                    slots[key] = value
                else:
                    invalid.append(key)
            primary = route.scenarios[0]
            scenario = self.catalog.scenarios.get(primary.scenario_id)
            low_confidence = session.low_confidence + 1 if primary.confidence < .45 else 0
            decision, active = "execute", primary.scenario_id if scenario else None
            missing, actions, handoff = [], [], None
            warnings = [{"stage": "slots", "code": "invalid_input", "message": f"Некорректный слот: {k}"} for k in invalid]
            if primary.scenario_id == "SYS_GOODBYE":
                decision = "goodbye"
            elif primary.scenario_id == "SYS_OUT_OF_SCOPE":
                decision = "out_of_scope"
            elif primary.scenario_id == "SYS_UNCLEAR" or primary.confidence < .75:
                decision, active = "clarify", session.active_scenario
            always_handoff = bool(scenario) and (scenario.get("handoff") or {}).get("when") == "always"
            if low_confidence >= 2 or always_handoff:
                decision = "handoff"
                queue = (scenario.get("handoff") or {}).get("queue", "operator_general") if always_handoff else "operator_general"
                handoff = {"queue": queue, "summary": request.text}
            elif scenario and decision == "execute":
                required = scenario["slots"]["required"]
                missing = [name for name in required if slots.get(name) in (None, "", [])]
                # Re-ask only required slots the model filled with a bad value.
                missing.extend(k for k in invalid if k in required and k not in missing)
                if missing:
                    decision = "collect_slots"
                else:
                    decision, actions, handoff = self._read_only(scenario, slots, request.text)
            queued = list(dict.fromkeys([s.scenario_id for s in route.scenarios[1:]] + session.queued_scenarios))
            if session.active_scenario and not route.is_continuation and session.active_scenario != active:
                queued.append(session.active_scenario)
            queued = [q for q in dict.fromkeys(queued) if q != active]
            context = {
                "decision": decision, "response_language": route.response_language,
                "reason": route.reason, "slots": slots, "missing_slots": missing,
                "slot_prompt": self.catalog.slots[missing[0]]["prompt"][route.response_language] if missing else None,
                "actions": actions, "handoff": handoff, "queued_scenarios": queued,
                "knowledge": self.catalog.knowledge,
            }
            reply_start = perf_counter()
            reply = await self.router.reply(request.text, context)
            result = {
                "session_id": session_id, "request_id": request.request_id, "turn_id": str(uuid4()),
                "turn": len(session.results) + 1, "mode": "live", "transcript": request.text,
                "language": route.language, "response_language": route.response_language,
                "scenarios": [s.model_dump() for s in route.scenarios],
                "alternatives": [s.model_dump() for s in route.alternatives], "reason": route.reason,
                "is_continuation": route.is_continuation, "decision": decision,
                "active_scenario": active, "queued_scenarios": queued, "slots": slots,
                "missing_slots": missing, "actions": actions, "pending_confirmation": None,
                "handoff": handoff, "reply": reply, "audio_url": None,
                "latency_ms": {"stt": None, "triage": None, "router": router_ms,
                               "response": (perf_counter() - reply_start) * 1000,
                               "tts_first_audio": None, "total": None},
                "server_processing_ms": (perf_counter() - start) * 1000, "warnings": warnings,
            }
            session.slots, session.queued_scenarios = slots, queued
            session.active_scenario = active if decision in {"collect_slots", "clarify"} else None
            session.low_confidence = low_confidence
            session.history.extend([{"role": "user", "content": request.text}, {"role": "assistant", "content": reply}])
            session.results[request.request_id] = deepcopy(result)
            return result

    def _read_only(self, scenario, slots, text):
        names = scenario["actions"]
        # Only these read-only action paths are implemented in the transport slice.
        # send_sms is optional and never reported as sent.
        if "get_offices" in names or "list_clinics" in names:
            name = "get_offices" if "get_offices" in names else "list_clinics"
            key = "offices" if name == "get_offices" else "clinics"
            rows = [row for row in self.catalog.knowledge[key] if row["city"].casefold() == slots["city"].casefold()]
            if rows:
                return "execute", [{"name": name, "mode": "execute", "status": "ok", "result": {key: rows}}], None
            return "execute", [{"name": name, "mode": "execute", "status": "error", "error": {"code": "not_found", "message": "В базе нет результатов для этого города"}}], None
        if "kb_lookup" in names and all(n in {"kb_lookup", "send_sms"} for n in names):
            return "execute", [{"name": "kb_lookup", "mode": "execute", "status": "ok", "result": {"source": "knowledge_base.json", "scenario_id": scenario["scenario_id"]}}], None
        queue = (scenario.get("handoff") or {}).get("queue", "operator_general")
        return "handoff", [], {"queue": queue, "summary": f"{text} — исполнитель действий {', '.join(names)} ещё не подключён; изменений данных не было."}
