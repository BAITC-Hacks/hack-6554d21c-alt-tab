import json
from types import SimpleNamespace

import pytest

from backend.catalog import Catalog
from backend.config import Settings
from backend.router import ProviderError, Router


def answer(**changes):
    value = {"scenarios": [{"scenario_id": "SC33", "confidence": .95}], "alternatives": [],
             "language": "ru", "response_language": "ru", "reason": "Запрос адреса офиса",
             "slots": {"city": "Almaty"}, "is_continuation": False}
    value.update(changes)
    return value


class LLMStub:
    def __init__(self, output):
        self.output, self.calls = output, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(self.output)))])


async def test_catalog_and_urgent_order_are_data_driven():
    catalog = Catalog()
    assert len(catalog.allowed_ids) == 43
    fake = LLMStub(answer(scenarios=[{"scenario_id": "SC33", "confidence": .9}, {"scenario_id": "SC11", "confidence": .9}]))
    router = Router(catalog, Settings(), fake)
    result = await router.route("Адрес офиса и ДТП прямо сейчас", {})
    assert [s.scenario_id for s in result.scenarios] == ["SC11", "SC33"]
    assert fake.calls[0]["model"] == "gpt-4.1-mini"
    assert "not_this_if" in fake.calls[0]["messages"][0]["content"]
    assert "2026-10-01" in fake.calls[0]["messages"][0]["content"]
    assert "expected" not in fake.calls[0]["messages"][1]["content"]


@pytest.mark.parametrize("output", [
    answer(scenarios=[{"scenario_id": "SC99", "confidence": .9}]),
    answer(scenarios=[{"scenario_id": "SC33", "confidence": 2}]),
    answer(slots={"invented_slot": "value"}),
    answer(language="en"),
])
async def test_invalid_llm_decision_is_not_accepted(output):
    with pytest.raises(ProviderError):
        await Router(Catalog(), Settings(), LLMStub(output)).route("text", {})


async def test_missing_key_does_not_create_fake_prediction():
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        await Router(Catalog(), Settings()).route("Где офис?", {})
