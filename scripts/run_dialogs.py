"""Живой прогон dialogs_sample.json через HTTP API backend'а.

Запуск (backend должен слушать --base, например `scripts/dev.py`):

    .venv/Scripts/python scripts/run_dialogs.py
    .venv/Scripts/python scripts/run_dialogs.py --dialog D07,D08 --out artifacts/dialogs_report.md

Для каждого диалога создаётся новая сессия, каждая client-реплика отправляется в
POST /api/sessions/{id}/turns. В API уходит только text; ожидаемые сценарии и слоты
из JSON используются лишь для сравнения в отчёте.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "case" / "dialogs_sample.json"
TIMEOUT_S = 90


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


class HttpFailure(Exception):
    def __init__(self, status: int | str, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def call(method: str, url: str, body: dict | None = None) -> dict:
    try:
        return http_json(method, url, body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HttpFailure(exc.code, raw[:300]) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpFailure("conn", str(exc)[:300]) from exc


def fmt_actions(actions: list[dict] | None) -> str:
    if not actions:
        return "-"
    parts = []
    for a in actions:
        parts.append(
            f"{a.get('name')}:{a.get('mode') or '-'}:{a.get('status') or '-'}"
        )
    return ",".join(parts)


def short(text: str | None, n: int = 120) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def run_dialog(base: str, dialog: dict, rows: list[dict], errors: list[str]) -> None:
    did = dialog["dialog_id"]
    try:
        session = call("POST", f"{base}/api/sessions", {})
        sid = session["session_id"]
    except HttpFailure as exc:
        msg = f"{did} | session create failed | {exc}"
        print(msg)
        errors.append(msg)
        return
    print(f"{did} | session {sid} | {dialog.get('title', '')}")

    turn_no = 0
    for turn in dialog["turns"]:
        if turn.get("role") != "client":
            continue
        turn_no += 1
        expected = list(turn.get("scenarios") or [])
        text = turn["text"]
        row = {
            "dialog": did,
            "turn": turn_no,
            "lang": turn.get("lang", ""),
            "text": text,
            "expected": expected,
        }
        t0 = time.perf_counter()
        try:
            res = call(
                "POST",
                f"{base}/api/sessions/{sid}/turns",
                {"request_id": str(uuid.uuid4()), "text": text},
            )
        except HttpFailure as exc:
            row.update(error=f"HTTP {exc.status}: {exc.body}")
            rows.append(row)
            msg = f"{did} t{turn_no} | expected {','.join(expected) or '-'} | ERROR {exc}"
            print(msg)
            errors.append(msg)
            return  # завершить этот диалог, продолжить остальные
        wall_ms = (time.perf_counter() - t0) * 1000

        got_list = [s.get("scenario_id") for s in res.get("scenarios") or []]
        conf = None
        if res.get("scenarios"):
            conf = (res["scenarios"][0] or {}).get("confidence")
        queued = list(res.get("queued_scenarios") or [])
        primary_hit = bool(expected) and bool(got_list) and expected[0] == got_list[0]
        multi_hit = set(expected) <= set(got_list) | set(queued)
        router_ms = (res.get("latency_ms") or {}).get("router")

        row.update(
            got=got_list,
            confidence=conf,
            queued=queued,
            decision=res.get("decision"),
            active=res.get("active_scenario"),
            actions=fmt_actions(res.get("actions")),
            pending=bool(res.get("pending_confirmation")),
            handoff=(res.get("handoff") or {}).get("queue") if res.get("handoff") else None,
            language=res.get("language"),
            reply=res.get("reply") or "",
            router_ms=router_ms,
            wall_ms=round(wall_ms),
            primary_hit=primary_hit,
            multi_hit=multi_hit,
        )
        rows.append(row)

        conf_s = f" ({conf:.2f})" if isinstance(conf, (int, float)) else ""
        print(
            f"{did} t{turn_no} | expected {','.join(expected) or '-'} | "
            f"got {','.join(got_list) or '-'}{conf_s}"
            + (f" +queued {','.join(queued)}" if queued else "")
            + f" | decision={res.get('decision')} | actions={row['actions']} | "
            f'reply="{short(row["reply"])}"'
        )


def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_report(path: Path, base: str, rows: list[dict], errors: list[str], summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Прогон dialogs_sample.json",
        "",
        f"- API: `{base}`",
        f"- Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Ходов клиента отправлено: {summary['turns']} (с ответом: {summary['answered']})",
        f"- Primary hits: {summary['primary']} / {summary['answered']} ({summary['primary_rate']:.3f})",
        f"- Multi hits: {summary['multi']} / {summary['answered']} ({summary['multi_rate']:.3f})",
        f"- Средний router latency: {summary['router_avg']}",
        f"- Средний HTTP wall time: {summary['wall_avg']}",
        f"- Ошибок HTTP: {summary['errors']}",
        "",
        "Запуск: `.venv/Scripts/python scripts/run_dialogs.py --base " + base + " [--dialog D01,D07] [--out artifacts/dialogs_report.md]`",
        "",
        "| Диалог | Ход | Lang | Реплика | Ожидалось | Получено | Conf | Queued | Decision | Actions | Pending | Handoff | Router мс | Primary | Multi | Ответ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(
                f"| {r['dialog']} | {r['turn']} | {r['lang']} | {md_escape(short(r['text'], 80))} | "
                f"{','.join(r['expected'])} | ERROR | | | | | | | | | | {md_escape(r['error'])} |"
            )
            continue
        conf = f"{r['confidence']:.2f}" if isinstance(r.get("confidence"), (int, float)) else "-"
        lines.append(
            f"| {r['dialog']} | {r['turn']} | {r['lang']} | {md_escape(short(r['text'], 80))} | "
            f"{','.join(r['expected']) or '-'} | {','.join(r['got']) or '-'} | {conf} | "
            f"{','.join(r['queued']) or '-'} | {r['decision']} | {md_escape(r['actions'])} | "
            f"{'yes' if r['pending'] else '-'} | {r['handoff'] or '-'} | "
            f"{r['router_ms'] if r['router_ms'] is not None else '-'} | "
            f"{'+' if r['primary_hit'] else '-'} | {'+' if r['multi_hit'] else '-'} | "
            f"{md_escape(short(r['reply'], 160))} |"
        )
    if errors:
        lines += ["", "## Ошибки", ""] + [f"- {md_escape(e)}" for e in errors]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Живой прогон dialogs_sample.json через API backend'а")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="базовый URL API")
    ap.add_argument("--dialog", default="", help="фильтр dialog_id, через запятую: D01,D07")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="путь к dialogs_sample.json")
    ap.add_argument("--out", default="artifacts/dialogs_report.md", help="Markdown-отчёт")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    dialogs = data["dialogs"]
    if args.dialog:
        wanted = {d.strip() for d in args.dialog.split(",") if d.strip()}
        dialogs = [d for d in dialogs if d["dialog_id"] in wanted]
        missing = wanted - {d["dialog_id"] for d in dialogs}
        if missing:
            print(f"Не найдены диалоги: {', '.join(sorted(missing))}")
    if not dialogs:
        print("Нет диалогов для прогона")
        return 2

    rows: list[dict] = []
    errors: list[str] = []
    for dialog in dialogs:
        run_dialog(base, dialog, rows, errors)
        print()

    answered = [r for r in rows if "error" not in r]
    primary = sum(1 for r in answered if r["primary_hit"])
    multi = sum(1 for r in answered if r["multi_hit"])
    router_vals = [r["router_ms"] for r in answered if isinstance(r.get("router_ms"), (int, float))]
    wall_vals = [r["wall_ms"] for r in answered]
    summary = {
        "turns": len(rows),
        "answered": len(answered),
        "primary": primary,
        "multi": multi,
        "primary_rate": primary / len(answered) if answered else 0.0,
        "multi_rate": multi / len(answered) if answered else 0.0,
        "router_avg": f"{statistics.mean(router_vals):.0f} мс ({len(router_vals)} замеров)" if router_vals else "не измерено",
        "wall_avg": f"{statistics.mean(wall_vals):.0f} мс" if wall_vals else "не измерено",
        "errors": len(errors),
    }
    print("=== Сводка ===")
    print(f"Ходов: {summary['turns']} (с ответом {summary['answered']})")
    print(f"Primary hits: {primary}/{summary['answered']} = {summary['primary_rate']:.3f}")
    print(f"Multi hits:   {multi}/{summary['answered']} = {summary['multi_rate']:.3f}")
    print(f"Средний router latency: {summary['router_avg']}; HTTP wall: {summary['wall_avg']}")
    print(f"Ошибок HTTP: {summary['errors']}")

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    write_report(out, base, rows, errors, summary)
    print(f"Отчёт: {out}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
