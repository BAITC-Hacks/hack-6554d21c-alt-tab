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
from backend.router import ProviderError, Router  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/predictions.json")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    router = Router(Catalog(), Settings.from_env())
    rows = json.loads((ROOT / "case" / "dev_utterances.json").read_text(encoding="utf-8"))["utterances"]
    inputs = [{"id": row["id"], "text": row["text"]} for row in rows]
    predictions, failed, done = {}, [], 0
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(item):
        nonlocal done
        async with semaphore:
            try:
                route = await router.route(item["text"], {})
                predictions[item["id"]] = [s.scenario_id for s in route.scenarios]
            except ProviderError as exc:
                # One transient failure must not lose the other completed calls.
                predictions[item["id"]] = []
                failed.append((item["id"], str(exc)))
            done += 1
            print(f"{done}/{len(inputs)} {item['id']}", flush=True)

    try:
        await asyncio.gather(*(one(item) for item in inputs))
    finally:
        await router.close()
    destination = ROOT / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = {item["id"]: predictions[item["id"]] for item in inputs}
    destination.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    for utterance_id, error in failed:
        print(f"FAILED {utterance_id}: {error}")
    print(f"{len(inputs) - len(failed)}/{len(inputs)} predictions from the real router; {len(failed)} failed")
    print(f"python case/evaluate.py {args.output} case/dev_utterances.json")


if __name__ == "__main__":
    asyncio.run(main())
