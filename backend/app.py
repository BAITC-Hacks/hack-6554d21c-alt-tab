from contextlib import asynccontextmanager
from datetime import timedelta
import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from livekit import api

from .catalog import Catalog
from .config import Settings
from .models import TurnRequest
from .router import ProviderError, Router
from .service import RequestConflict, TurnService


def create_app(settings=None, router=None):
    settings = settings or Settings.from_env()
    catalog = Catalog()
    router = router or Router(catalog, settings)
    service = TurnService(catalog, router)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await router.close()

    app = FastAPI(title="Saqta Voice Router", lifespan=lifespan)
    app.state.service = service

    def error(status, code, message, retryable=False):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "retryable": retryable}})

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return error(503, "provider_unavailable", str(exc), True)

    @app.exception_handler(RequestConflict)
    async def conflict(request, exc):
        return error(409, "request_conflict", str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return error(422, "invalid_input", "Проверьте request_id и непустой текст до 4000 символов")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "live", "voice_ready": False,
                "voice_status": "not_live_verified", "voice_configured": not settings.missing_voice_config(),
                "missing_config": settings.missing_voice_config(), "transport": "livekit",
                "models": {"llm": settings.openai_model, "stt": settings.stt_model, "tts": settings.tts_model},
                "scenario_count": len(catalog.scenarios), "implementation": "transport_and_read_only_router"}

    @app.post("/api/sessions")
    async def new_session():
        session = service.create_session()
        return {"session_id": session.id, "as_of_date": catalog.as_of_date}

    @app.post("/api/sessions/{session_id}/turns")
    async def turn(session_id: str, body: TurnRequest):
        if session_id not in service.sessions:
            return error(404, "session_not_found", "Создайте новую сессию")
        return await service.handle_turn(session_id, body)

    @app.get("/api/sessions/{session_id}/turns")
    async def turns(session_id: str):
        if session_id not in service.sessions:
            return error(404, "session_not_found", "Создайте новую сессию")
        return {"turns": list(service.sessions[session_id].results.values())}

    @app.post("/api/sessions/{session_id}/livekit")
    async def join_livekit(session_id: str):
        if session_id not in service.sessions:
            return error(404, "session_not_found", "Создайте новую сессию")
        if settings.missing_voice_config():
            return error(503, "voice_not_configured", "Не настроены: " + ", ".join(settings.missing_voice_config()))
        room_name = f"saqta-{session_id}"
        # Explicit dispatch attached to the participant token: the job starts only
        # after browser microphone permission and a successful room connection.
        metadata = json.dumps({"session_id": session_id})
        token = (api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
                 .with_identity(f"client-{session_id}")
                 .with_ttl(timedelta(minutes=15))
                 .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True,
                                             can_subscribe=True, can_publish_data=True))
                 .with_room_config(api.RoomConfiguration(
                     empty_timeout=60, departure_timeout=20,
                     agents=[api.RoomAgentDispatch(agent_name=settings.agent_name, metadata=metadata)]))
                 .to_jwt())
        return {"room": room_name, "token": token, "ws_url": settings.livekit_url,
                "session_id": session_id, "trace_topic": "saqta.trace"}

    @app.post("/api/sessions/{session_id}/audio")
    async def file_audio(session_id: str, request: Request):
        return error(501, "transport_changed", "Голос использует LiveKit; подключитесь через /livekit")

    return app


app = create_app()
