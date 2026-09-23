import asyncio
from copy import deepcopy

import pytest

from backend.catalog import Catalog
from backend.models import RouteDecision, TurnRequest
from backend.router import ProviderError
from backend.service import RequestConflict, TurnService


class ScriptedRouter:
    def __init__(self, scenario="SC33", slots=None, confidence=.95):
        self.scenario, self.slots, self.confidence = scenario, slots or {}, confidence
        self.calls, self.contexts = 0, []
        self.reply_fails = False

    async def route(self, text, state):
        self.calls += 1
        self.contexts.append(deepcopy(state))
        await asyncio.sleep(0)
        return RouteDecision(scenarios=[{"scenario_id": self.scenario, "confidence": self.confidence}],
                             alternatives=[], language="ru", response_language="ru",
                             reason="Test router", slots=self.slots, is_continuation=bool(state["active_scenario"]))

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


async def test_unsupported_irreversible_operation_is_not_success():
    catalog = Catalog()
    router = ScriptedRouter(scenario="SC28", slots={"policy_number": "SQ-OGPO-104501", "cancel_reason": "sale"})
    service = TurnService(catalog, router)
    session = service.create_session()
    before = deepcopy(session.data)
    result = await service.handle_turn(session.id, TurnRequest(request_id="a", text="Расторгните полис"))
    assert result["decision"] in {"collect_slots", "handoff"}
    assert result["actions"] == []
    assert session.data == before


async def test_two_low_confidence_turns_handoff():
    router = ScriptedRouter(confidence=.2)
    service = TurnService(Catalog(), router)
    session = service.create_session()
    await service.handle_turn(session.id, TurnRequest(request_id="a", text="Непонятно"))
    result = await service.handle_turn(session.id, TurnRequest(request_id="b", text="И ещё непонятно"))
    assert result["decision"] == "handoff"
    assert result["handoff"]["queue"] == "operator_general"
