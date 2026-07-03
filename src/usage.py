"""API トークン使用量の記録。

各 generate_content 応答の usage_metadata を集計し、実行終了時に
output/<date>/usage.json へ書き出す。追加の API 課金は発生しない（応答に
同梱されるメタデータを読むだけ）。1 回の `python -m src.main` プロセス内で
モジュールレベルに貯めるだけなので、外部状態は持たない。
"""

from __future__ import annotations

import json
import logging

from src.config import load_config, output_dir, today_jst

logger = logging.getLogger(__name__)

_records: list[dict] = []


def _load_pricing() -> tuple[dict, float]:
    """config.yaml から単価表と為替を読む。無ければ空。"""
    try:
        p = load_config().get("pricing", {}) or {}
        return p.get("models", {}) or {}, float(p.get("usd_jpy", 0) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load pricing config: %s", e)
        return {}, 0.0


def _cost_usd(model: str, prompt: int, total: int, models: dict) -> float | None:
    """1 ステップ分のコスト(USD)。単価未登録なら None。

    output/thinking/audio/image の出力は output 単価で課金されるため、
    prompt を input 単価、残り(total-prompt)を output 単価で見積る。
    """
    rate = models.get(model)
    if not rate:
        return None
    in_rate = float(rate.get("input", 0)) / 1_000_000
    out_rate = float(rate.get("output", 0)) / 1_000_000
    billable_out = max(total - prompt, 0)
    return prompt * in_rate + billable_out * out_rate


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

    models, usd_jpy = _load_pricing()

    by_step = []
    cost_usd_total = 0.0
    priced_all = True
    for k, v in agg.items():
        step, model = k
        cost = _cost_usd(model, v["prompt"], v["total"], models)
        entry = {"step": step, "model": model, **v}
        if cost is not None:
            entry["cost_usd"] = round(cost, 6)
            if usd_jpy:
                entry["cost_jpy"] = round(cost * usd_jpy, 2)
            cost_usd_total += cost
        else:
            priced_all = False
            entry["cost_usd"] = None
        by_step.append(entry)

    totals = {
        "calls": sum(v["calls"] for v in agg.values()),
        "prompt": sum(v["prompt"] for v in agg.values()),
        "output": sum(v["output"] for v in agg.values()),
        "total": sum(v["total"] for v in agg.values()),
        "cost_usd": round(cost_usd_total, 6),
        "priced_all_steps": priced_all,
    }
    if usd_jpy:
        totals["cost_jpy"] = round(cost_usd_total * usd_jpy, 2)
        totals["usd_jpy"] = usd_jpy

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
    cost_str = f"${totals['cost_usd']:.4f}"
    if "cost_jpy" in totals:
        cost_str += f" (≈¥{totals['cost_jpy']:.1f})"
    if not priced_all:
        cost_str += " ※一部モデル単価未登録"
    logger.info(
        "Usage: %d calls, %d tokens, cost %s -> %s",
        totals["calls"], totals["total"], cost_str, path,
    )
    return summary
