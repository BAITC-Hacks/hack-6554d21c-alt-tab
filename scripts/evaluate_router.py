"""Generate predictions with the actual router. Never expose expected to it."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog import Catalog  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.router import Router  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/predictions.json")
    args = parser.parse_args()
    router = Router(Catalog(), Settings.from_env())
    rows = json.loads((ROOT / "dev_utterances.json").read_text(encoding="utf-8"))["utterances"]
    inputs = [{"id": row["id"], "text": row["text"]} for row in rows]
    predictions = {}
    try:
        for item in inputs:
            route = await router.route(item["text"], {})
            predictions[item["id"]] = [s.scenario_id for s in route.scenarios]
            print(f"{len(predictions)}/{len(inputs)} {item['id']}", flush=True)
    finally:
        await router.close()
    destination = ROOT / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"python evaluate.py {args.output} dev_utterances.json")


if __name__ == "__main__":
    asyncio.run(main())
