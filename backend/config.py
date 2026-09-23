from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(default="", repr=False)
    soniox_api_key: str = field(default="", repr=False)
    openai_model: str = "gpt-4.1-mini"
    stt_model: str = "stt-rt-v5"
    tts_model: str = "tts-rt-v2"
    voice: str = "Arthur"
    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str = field(default="devkey", repr=False)
    livekit_api_secret: str = field(default="secret", repr=False)
    agent_name: str = "saqta-router"
    backend_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            soniox_api_key=os.getenv("SONIOX_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            stt_model=os.getenv("SONIOX_STT_MODEL", "stt-rt-v5"),
            tts_model=os.getenv("SONIOX_TTS_MODEL", "tts-rt-v2"),
            voice=os.getenv("SONIOX_VOICE", "Arthur"),
            livekit_url=os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880"),
            livekit_api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
            livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", "secret"),
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "saqta-router"),
            backend_url=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        )

    def missing_voice_config(self):
        names = {
            "OPENAI_API_KEY": self.openai_api_key,
            "SONIOX_API_KEY": self.soniox_api_key,
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key,
            "LIVEKIT_API_SECRET": self.livekit_api_secret,
        }
        return [name for name, value in names.items() if not value]

