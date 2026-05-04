"""画像生成プロンプト試行用スクリプト。

使い方:
  .venv/bin/python tools/test_image_gen.py cover "ここにプロンプト"
  .venv/bin/python tools/test_image_gen.py episode "ここにプロンプト"

出力: tools/samples/{cover|episode}_YYYYMMDD_HHMMSS.png
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from src.config import PROJECT_ROOT  # ロガー抑制が自動適用される

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MODELS = {
    "cover": "gemini-3-pro-image-preview",      # Nano Banana Pro
    "episode": "gemini-3.1-flash-image-preview", # Nano Banana 2
}


def generate(kind: str, prompt: str) -> Path:
    if kind not in MODELS:
        raise ValueError(f"kind must be one of {list(MODELS.keys())}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    model = MODELS[kind]
    logger.info("Generating with %s ...", model)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    parts = response.candidates[0].content.parts
    image_data = None
    for p in parts:
        if hasattr(p, "inline_data") and p.inline_data and p.inline_data.data:
            image_data = p.inline_data.data
            break
    if not image_data:
        raise RuntimeError("No image in response")

    out_dir = PROJECT_ROOT / "tools" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{kind}_{timestamp}.png"
    out_path.write_bytes(image_data)
    logger.info("Saved: %s (%d KB)", out_path, len(image_data) // 1024)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    path = generate(sys.argv[1], sys.argv[2])
    print(f"OPEN: {path}")
