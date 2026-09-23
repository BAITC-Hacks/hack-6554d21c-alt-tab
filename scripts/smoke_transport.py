"""Check actual local HTTP/WebRTC without calling paid speech/LLM APIs."""
import asyncio
from pathlib import Path
import sys
from uuid import uuid4

import httpx
from livekit import api, rtc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Settings  # noqa: E402


async def main():
    settings = Settings.from_env()
    async with httpx.AsyncClient(base_url=settings.backend_url) as http:
        response = await http.get("/api/health")
        response.raise_for_status()
        print("HTTP: OK; models:", response.json()["models"])
    room_name = "saqta-transport-smoke-" + uuid4().hex
    token = (api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
             .with_identity("transport-test")
             .with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt())
    room = rtc.Room()
    try:
        await asyncio.wait_for(room.connect(settings.livekit_url, token), timeout=20)
        print("WebRTC: connected to", room.name)
    finally:
        await room.disconnect()
        async with api.LiveKitAPI(settings.livekit_url, settings.livekit_api_key,
                                  settings.livekit_api_secret) as client:
            await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
    print("PASS: transport only. Microphone, STT, LLM and TTS are not tested here.")


if __name__ == "__main__":
    asyncio.run(main())
