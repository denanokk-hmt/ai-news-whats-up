from __future__ import annotations

import logging
import os
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from src.config import PROJECT_ROOT, output_dir, today_jst
from src.retry import with_retry

logger = logging.getLogger(__name__)


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    # timeout は HTTP レイヤの無限ハング防止。
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=600_000),  # 10 分
    )


def _extract_image(response) -> bytes:
    for p in response.candidates[0].content.parts:
        if hasattr(p, "inline_data") and p.inline_data and p.inline_data.data:
            return p.inline_data.data
    raise RuntimeError("No image in response")


def pick_main_topic(articles: list[dict]) -> str:
    """重要度が最も高い記事のタイトルを返す（エピソード画像のテーマ）。"""
    if not articles:
        return "AIニュース"
    top = max(articles, key=lambda a: a.get("importance", 0))
    return top.get("japanese_title") or top.get("original_title") or "AIニュース"


def _optimize_for_apple_podcasts(image_data: bytes, target_size: int = 3000, max_kb: int = 500) -> bytes:
    """Apple Podcasts要件（3000x3000、JPG、500KB以下）に最適化。"""
    import io
    src = Image.open(io.BytesIO(image_data)).convert("RGB")
    upscaled = src.resize((target_size, target_size), Image.Resampling.LANCZOS)
    # 品質を段階的に下げてサイズを調整
    for q in [85, 80, 75, 72, 68, 65]:
        buf = io.BytesIO()
        upscaled.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        size_kb = buf.tell() // 1024
        if size_kb <= max_kb:
            logger.info("Optimized: %dx%d, q=%d, %dKB", target_size, target_size, q, size_kb)
            return buf.getvalue()
    # 最低品質でもオーバー時はそれを返す
    return buf.getvalue()


def generate_episode_image(
    articles: list[dict],
    cover_path: Path,
    instruction_template: str,
    model: str,
) -> Path:
    """カバーをベースに編集モードで当日エピソード画像を生成。"""
    if not cover_path.exists():
        raise FileNotFoundError(f"Cover image not found: {cover_path}")

    topic = pick_main_topic(articles)
    date_str = today_jst().strftime("%Y.%m.%d")
    instruction = instruction_template.format(topic=topic, date=date_str)

    src_image = Image.open(cover_path)
    client = _client()

    logger.info("Generating episode image (%s) for topic: %s", model, topic[:60])
    response = with_retry(
        client.models.generate_content,
        model=model,
        contents=[instruction, src_image],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    image_data = _extract_image(response)
    # Apple Podcasts要件に最適化
    optimized = _optimize_for_apple_podcasts(image_data)

    out_path = output_dir() / "episode_image.jpg"
    out_path.write_bytes(optimized)
    logger.info("Saved episode image: %s (%d KB)", out_path, len(optimized) // 1024)
    return out_path


def ensure_cover_exists(cover_path: Path) -> Path:
    """カバー画像が存在することを確認。なければエラー（手動配置必須）。"""
    if not cover_path.is_absolute():
        cover_path = PROJECT_ROOT / cover_path
    if not cover_path.exists():
        raise FileNotFoundError(
            f"Cover image not found: {cover_path}. "
            "Place a 1400x1400+ square PNG/JPG at this path."
        )
    return cover_path
