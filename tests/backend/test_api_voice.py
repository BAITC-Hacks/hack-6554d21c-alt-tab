import json

from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from backend.app import create_app
from backend.config import Settings
from backend.voice import SaqtaAgent, stt_options, turn_options
from livekit.agents import llm


def test_missing_keys_and_invalid_input_are_honest():
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/health").json()["voice_ready"] is False
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        result = client.post(f"/api/sessions/{session_id}/turns", json={"request_id": "a", "text": "Где офис?"})
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "provider_unavailable"
        assert client.post(f"/api/sessions/{session_id}/livekit").status_code == 503
        assert client.post(f"/api/sessions/{session_id}/turns", json={"request_id": "a", "text": "  "}).status_code == 422
        assert client.post("/api/sessions/unknown/turns", json={"request_id": "a", "text": "hello"}).status_code == 404


def test_livekit_token_is_room_scoped_with_named_dispatch():
    settings = Settings(openai_api_key="test-openai", soniox_api_key="test-soniox",
                        livekit_api_secret="test-secret-long-enough-for-signing-123456")
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]
        result = client.post(f"/api/sessions/{session_id}/livekit")
        assert result.status_code == 200
        body = result.json()
        payload = jwt.decode(body["token"], settings.livekit_api_secret, algorithms=["HS256"])
        assert payload["video"]["room"] == "saqta-" + session_id
        assert payload["roomConfig"]["agents"][0]["agentName"] == "saqta-router"
        assert json.loads(payload["roomConfig"]["agents"][0]["metadata"])["session_id"] == session_id
        assert "test-soniox" not in result.text
        assert "test-openai" not in result.text


async def test_voice_calls_same_text_api_and_emits_trace():
    requests, packets, languages = [], [], []
    result = {"reply": "Алматыдағы кеңсе", "response_language": "kk", "turn_id": "t1"}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=result)

    class Speech:
        def update_options(self, **options):
            languages.append(options["language"])

    async def publish(topic, payload):
        packets.append((topic, payload))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as http:
        agent = SaqtaAgent("session1", http, Speech(), publish)
        context = llm.ChatContext()
        context.add_message(role="user", content="Кеңсе қайда?")
        chunks = [chunk async for chunk in agent.llm_node(context, [], None)]
    assert chunks == [result["reply"]]
    assert requests[0].url.path == "/api/sessions/session1/turns"
    assert json.loads(requests[0].content)["text"] == "Кеңсе қайда?"
    assert packets == [("saqta.trace", result)]
    assert languages == ["kk"]


async def test_voice_provider_failure_does_not_emit_success():
    packets = []

    async def publish(topic, payload):
        packets.append((topic, payload))

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)), base_url="http://test") as http:
        agent = SaqtaAgent("session1", http, None, publish)
        context = llm.ChatContext()
        context.add_message(role="user", content="Где офис?")
        spoken = [chunk async for chunk in agent.llm_node(context, [], None)]
    # The caller hears the error itself, never a made-up answer, and no trace is published.
    assert [topic for topic, _ in packets] == ["saqta.error"]
    assert spoken == [packets[0][1]["message"]]


def test_reused_soniox_config_has_ru_kk_and_no_speculative_actions():
    options = stt_options(Settings())
    assert options.language_hints == ["ru", "kk"]
    assert options.model == "stt-rt-v5"
    assert turn_options()["preemptive_generation"]["enabled"] is False
    assert turn_options()["interruption"]["mode"] == "vad"
