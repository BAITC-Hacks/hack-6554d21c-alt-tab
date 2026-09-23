"""LiveKit/Soniox voice pipeline.

All business decisions go through the HTTP turn service;
the LiveKit process never holds a second copy of business state.
"""
import asyncio
import json
import logging

import httpx
from livekit.agents import (
    Agent, AgentSession, InterruptionOptions, JobContext, TurnHandlingOptions,
    WorkerOptions, cli,
)
from livekit.plugins import openai, silero, soniox

from .config import Settings

logger = logging.getLogger("saqta.voice")


def stt_options(settings):
    # RU/KK hints and Soniox endpointing profile tuned for short call-centre turns.
    return soniox.STTOptions(
        model=settings.stt_model, language_hints=["ru", "kk"],
        language_hints_strict=False, enable_language_identification=True,
        max_endpoint_delay_ms=800, endpoint_latency_adjustment_level=2,
        endpoint_sensitivity=0.3,
    )


def turn_options():
    # Use local VAD for self-hosted LiveKit; no cloud interruption detector.
    # Never execute business turns speculatively on an interim transcript.
    return TurnHandlingOptions(
        turn_detection="stt",
        interruption=InterruptionOptions(mode="vad", min_words=1),
        preemptive_generation={"enabled": False},
    )


class SaqtaAgent(Agent):
    def __init__(self, session_id, http, speech, publish):
        super().__init__(instructions="Replies are supplied by the Saqta backend router.")
        self.session_id, self.http, self.speech, self.publish = session_id, http, speech, publish

    async def llm_node(self, chat_ctx, tools, model_settings):
        message = next((m for m in reversed(chat_ctx.items)
                        if getattr(m, "role", None) == "user" and getattr(m, "text_content", None)), None)
        if message is None:
            return
        request_id = f"voice-{message.id}"
        try:
            response = await self.http.post(
                f"/api/sessions/{self.session_id}/turns",
                json={"request_id": request_id, "text": message.text_content},
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError):
            message = "Не удалось обработать реплику. Повторите запрос."
            await self.publish("saqta.error", {"stage": "router", "request_id": request_id,
                                               "message": message})
            # A voice-only caller must hear that the turn failed, not silence.
            yield message
            return
        self.speech.update_options(language=result["response_language"])
        await self.publish("saqta.trace", result)
        yield result["reply"]


async def entrypoint(ctx: JobContext):
    settings = Settings.from_env()
    metadata = json.loads(ctx.job.metadata or "{}")
    session_id = metadata.get("session_id")
    # ctx.room.name is empty before connect(); the job carries the room name.
    if not session_id or ctx.job.room.name != f"saqta-{session_id}":
        raise ValueError("Invalid Saqta room metadata")
    await ctx.connect()
    http = httpx.AsyncClient(base_url=settings.backend_url, timeout=95)
    ctx.add_shutdown_callback(http.aclose)

    async def publish(topic, payload):
        await ctx.room.local_participant.publish_data(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"), reliable=True, topic=topic,
        )

    speech = soniox.TTS(api_key=settings.soniox_api_key, model=settings.tts_model,
                        voice=settings.voice, language="ru", speed=1.3)
    speech.prewarm()
    session = AgentSession(
        stt=soniox.STT(api_key=settings.soniox_api_key, params=stt_options(settings)),
        # Required pipeline interface; SaqtaAgent.llm_node overrides generation
        # and calls the shared HTTP handler instead of a second LLM conversation.
        llm=openai.LLM(api_key=settings.openai_api_key, model=settings.openai_model),
        tts=speech, vad=silero.VAD.load(activation_threshold=.6, min_silence_duration=.28),
        turn_handling=turn_options(), user_away_timeout=60,
    )
    pending = set()

    @session.on("error")
    def on_error(event):
        # Do not forward provider messages: they can contain credentials or URLs.
        task = asyncio.create_task(publish("saqta.error", {
            "stage": "voice", "message": "Ошибка голосового провайдера. Текст доступен в трассировке."
        }))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def cleanup():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    ctx.add_shutdown_callback(cleanup)
    await session.start(room=ctx.room, agent=SaqtaAgent(session_id, http, speech, publish))
    await publish("saqta.ready", {"session_id": session_id, "mode": "live"})
    # The greeting is Kazakh; each reply is then voiced in the language the router chose.
    speech.update_options(language="kk")
    session.say("Сәлеметсіз бе! Мен Saqta ИИ-көмекшісімін. Сізге қалай көмектесе аламын?")


def main():
    settings = Settings.from_env()
    missing = settings.missing_voice_config()
    if missing:
        raise SystemExit("Не настроены: " + ", ".join(missing))
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint, agent_name=settings.agent_name,
        ws_url=settings.livekit_url, api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    ))


if __name__ == "__main__":
    main()
