"""Start the local LiveKit, FastAPI and voice worker without production services."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-only", action="store_true", help="Run API without voice; real LLM still needs a key")
    parser.add_argument("--external-livekit", action="store_true", help="Use an already started LiveKit")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not args.text_only and settings.missing_voice_config():
        raise SystemExit("Заполните .env: " + ", ".join(settings.missing_voice_config()))
    processes = []
    docker_started = False
    try:
        if not args.text_only and not args.external_livekit:
            native = ROOT / ".cache/livekit/livekit-server.exe"
            if sys.platform == "win32" and native.exists():
                processes.append(subprocess.Popen([str(native), "--dev", "--bind", "127.0.0.1"], cwd=ROOT))
            else:
                subprocess.run(["docker", "compose", "up", "-d", "livekit"], cwd=ROOT, check=True)
                docker_started = True
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                                           "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT))
        if not args.text_only:
            processes.append(subprocess.Popen([sys.executable, "-m", "backend.voice", "start"], cwd=ROOT))
        print("API: http://127.0.0.1:8000/docs | Ctrl+C stops the processes started here", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(.5)
        raise SystemExit("Один из процессов остановился; смотрите ошибку выше")
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                if os.name == "nt":
                    # The venv redirector can spawn another python.exe. Stop the
                    # process tree owned by this launcher, not just its parent.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        if docker_started:
            subprocess.run(["docker", "compose", "stop", "livekit"], cwd=ROOT, check=False)


if __name__ == "__main__":
    main()
