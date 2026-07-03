"""API トークン使用量の記録。

各 generate_content 応答の usage_metadata を集計し、実行終了時に
output/<date>/usage.json へ書き出す。追加の API 課金は発生しない（応答に
同梱されるメタデータを読むだけ）。1 回の `python -m src.main` プロセス内で
モジュールレベルに貯めるだけなので、外部状態は持たない。
"""

from __future__ import annotations

import json
import logging

from src.config import output_dir, today_jst

logger = logging.getLogger(__name__)

_records: list[dict] = []


def record(step: str, model: str, response) -> None:
    """1 応答分の usage_metadata を記録する。取れなければ何もしない。"""
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return
    rec = {
        "step": step,
        "model": model,
        "prompt": int(getattr(um, "prompt_token_count", 0) or 0),
        # 音声/画像の出力トークンもここに含まれる（modality 別内訳は API 依存）
        "output": int(getattr(um, "candidates_token_count", 0) or 0),
        "total": int(getattr(um, "total_token_count", 0) or 0),
    }
    _records.append(rec)
    logger.info(
        "usage[%s] model=%s prompt=%d output=%d total=%d",
        step, model, rec["prompt"], rec["output"], rec["total"],
    )


def reset() -> None:
    _records.clear()


def flush() -> dict | None:
    """集計して output/<date>/usage.json に書き出す。記録が無ければ None。"""
    if not _records:
        logger.info("No usage records to flush")
        return None

    agg: dict[tuple[str, str], dict] = {}
    for r in _records:
        a = agg.setdefault(
            (r["step"], r["model"]),
            {"calls": 0, "prompt": 0, "output": 0, "total": 0},
        )
        a["calls"] += 1
        a["prompt"] += r["prompt"]
        a["output"] += r["output"]
        a["total"] += r["total"]

    by_step = [
        {"step": k[0], "model": k[1], **v} for k, v in agg.items()
    ]
    totals = {
        "calls": sum(v["calls"] for v in agg.values()),
        "prompt": sum(v["prompt"] for v in agg.values()),
        "output": sum(v["output"] for v in agg.values()),
        "total": sum(v["total"] for v in agg.values()),
    }
    summary = {
        "collected_at": today_jst().isoformat(),
        "totals": totals,
        "by_step": by_step,
        "records": _records,
    }
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "usage.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "Usage: %d calls, total %d tokens (prompt %d / output %d) -> %s",
        totals["calls"], totals["total"], totals["prompt"], totals["output"], path,
    )
    return summary
