import asyncio
from copy import deepcopy

import pytest

from backend.catalog import Catalog
from backend.models import RouteDecision, ScenarioChoice, TurnRequest
from backend.router import ProviderError
from backend.service import RequestConflict, TurnService


class ScriptedRouter:
    def __init__(self, scenario="SC33", slots=None, confidence=.95):
        self.scenario, self.slots, self.confidence = scenario, slots or {}, confidence
        self.calls, self.contexts = 0, []
        self.reply_fails = False
        self.confirmation, self.handoff_reason = None, None

    async def route(self, text, state):
        self.calls += 1
        self.contexts.append(deepcopy(state))
        await asyncio.sleep(0)
        return RouteDecision(scenarios=[{"scenario_id": self.scenario, "confidence": self.confidence}],
                             alternatives=[], language="ru", response_language="ru",
                             reason="Test router", slots=self.slots, is_continuation=bool(state["active_scenario"]),
                             confirmation=self.confirmation, handoff_reason=self.handoff_reason)

    async def reply(self, text, context):
        if self.reply_fails:
            raise ProviderError("test failure")
        return "Test response"

    async def close(self):
        pass


async def test_concurrent_retries_only_call_router_once():
    router = ScriptedRouter(slots={"city": "Almaty"})
    service = TurnService(Catalog(), router)
    session = service.create_session()
    request = TurnRequest(request_id="same", text="Где офис в Алматы?")
    a, b = await asyncio.gather(service.handle_turn(session.id, request), service.handle_turn(session.id, request))
    assert a == b
    assert router.calls == 1
    assert a["actions"][0]["result"]["offices"][0]["address"] == "Abai Ave 150"
    assert a["latency_ms"]["total"] is None
    with pytest.raises(RequestConflict):
        await service.handle_turn(session.id, TurnRequest(request_id="same", text="Другой текст"))


async def test_slot_continuation_keeps_session_context():
    router = ScriptedRouter()
    service = TurnService(Catalog(), router)
    session = service.create_session()
    first = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Где офис?"))
    assert first["decision"] == "collect_slots"
    assert first["missing_slots"] == ["city"]
    router.slots = {"city": "Almaty"}
    second = await service.handle_turn(session.id, TurnRequest(request_id="b", text="Алматы"))
    assert second["is_continuation"]
    assert router.contexts[1]["active_scenario"] == "SC33"
    assert second["decision"] == "execute"


async def test_provider_failure_leaves_state_unchanged():
    router = ScriptedRouter(slots={"city": "Almaty"})
    router.reply_fails = True
    service = TurnService(Catalog(), router)
    session = service.create_session()
    with pytest.raises(ProviderError):
        await service.handle_turn(session.id, TurnRequest(request_id="a", text="Алматы"))
    assert session.slots == {}
    assert session.history == []
    assert session.results == {}


async def test_irreversible_operation_stops_at_preview_until_consent():
    catalog = Catalog()
    router = ScriptedRouter(scenario="SC28", slots={"policy_number": "SQ-CASCO-204350", "cancel_reason": "Car sold"})
    service = TurnService(catalog, router)
    session = service.create_session()
    before = deepcopy(session.data)
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Расторгните полис"))
    assert result["decision"] == "confirm"
    preview = [a for a in result["actions"] if a["name"] == "cancel_policy"][0]
    assert preview["mode"] == "preview" and preview["result"]["refund_amount"] == 163800
    assert result["pending_confirmation"]["action"] == "cancel_policy"
    assert session.data == before  # nothing changed before consent
    # Refusal cancels the preview without touching data.
    router.slots, router.confirmation = {}, "no"
    result = await service.handle_turn(session.id, TurnRequest(request_id="b", text="Нет, подождите"))
    assert result["pending_confirmation"] is None and session.data == before
    # New preview, then explicit consent executes exactly once.
    router.confirmation = None
    result = await service.handle_turn(session.id, TurnRequest(request_id="c", text="Да, всё же расторгните"))
    assert result["decision"] == "confirm"
    router.confirmation = "yes"
    result = await service.handle_turn(session.id, TurnRequest(request_id="d", text="Да, подтверждаю"))
    executed = [a for a in result["actions"] if a["name"] == "cancel_policy"][0]
    assert executed["mode"] == "execute" and executed["status"] == "ok"
    assert result["pending_confirmation"] is None and result["decision"] == "execute"
    policy = [p for p in session.data["policies"] if p["policy_number"] == "SQ-CASCO-204350"][0]
    assert policy["status"] == "cancelled"
    # Replay of the same request does not execute again; a second "yes" has no pending action.
    replay = await service.handle_turn(session.id, TurnRequest(request_id="d", text="Да, подтверждаю"))
    assert replay == result
    again = await service.handle_turn(session.id, TurnRequest(request_id="e", text="Да"))
    assert not [a for a in again["actions"] if a["name"] == "cancel_policy" and a["mode"] == "execute" and a["status"] == "ok"]


async def test_identification_by_phone_fills_policy_and_unknown_client_is_reasked_once():
    catalog = Catalog()
    router = ScriptedRouter(scenario="SC25", slots={"phone": "+77010000008"})
    service = TurnService(catalog, router)
    session = service.create_session()
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Проверьте мой полис"))
    assert result["decision"] == "execute"
    names = [a["name"] for a in result["actions"]]
    assert names == ["find_client", "get_policy"]
    assert result["slots"]["policy_number"] == "SQ-OGPO-103990"
    router = ScriptedRouter(scenario="SC25", slots={"phone": "+77010000099"})
    service = TurnService(catalog, router)
    session = service.create_session()
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Проверьте полис"))
    assert result["decision"] == "collect_slots" and result["missing_slots"] == ["phone"]
    assert result["actions"][0]["status"] == "error" and result["actions"][0]["error"]["code"] == "not_found"
    result = await service.handle_turn(session.id, TurnRequest(request_id="b", text="+77010000099"))
    assert result["decision"] == "handoff"


async def test_multi_intent_runs_next_queued_scenario_after_primary():
    catalog = Catalog()
    router = ScriptedRouter(scenario="SC33", slots={"city": "Almaty"})
    service = TurnService(catalog, router)
    session = service.create_session()
    orig = router.route

    async def route(text, state):
        decision = await orig(text, state)
        decision.scenarios.append(ScenarioChoice(scenario_id="SC23", confidence=.8))
        return decision
    router.route = route
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Офис и клиники в Алматы"))
    assert [a["name"] for a in result["actions"]] == ["get_offices", "list_clinics"]
    assert result["queued_scenarios"] == []


async def test_two_low_confidence_turns_handoff():
    router = ScriptedRouter(confidence=.2)
    service = TurnService(Catalog(), router)
    session = service.create_session()
    await service.handle_turn(session.id, TurnRequest(request_id="a", text="Непонятно"))
    result = await service.handle_turn(session.id, TurnRequest(request_id="b", text="И ещё непонятно"))
    assert result["decision"] == "handoff"
    assert result["handoff"]["queue"] == "operator_general"


def test_slot_validation_follows_slots_json_types():
    slots = Catalog().slots
    from backend.service import valid_slot
    assert valid_slot(slots["drivers_iin"], ["123456789012"])
    assert not valid_slot(slots["drivers_iin"], ["12345"])
    assert not valid_slot(slots["drivers_iin"], [])
    assert valid_slot(slots["sum_insured"], 1000000)
    assert not valid_slot(slots["sum_insured"], 1234)
    assert valid_slot(slots["franchise"], 0)
    assert not valid_slot(slots["franchise"], False)


async def test_null_and_optional_slots_do_not_block_execution():
    router = ScriptedRouter(scenario="SC23", slots={"city": "Almaty", "doctor_specialty": None})
    service = TurnService(Catalog(), router)
    session = service.create_session()
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Клиники в Алматы"))
    assert result["decision"] == "execute"
    assert result["missing_slots"] == []
    assert result["warnings"] == []


async def test_always_handoff_comes_from_catalog():
    router = ScriptedRouter(scenario="SC37")
    service = TurnService(Catalog(), router)
    session = service.create_session()
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Дайте оператора"))
    assert result["decision"] == "handoff"
    assert result["handoff"]["queue"] == "operator_general"
