"""画像編集（既存画像をベースに指示で部分修正）

使い方:
  PYTHONPATH=. .venv/bin/python tools/edit_image.py <入力PNG> "編集指示"
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from src.config import PROJECT_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EDIT_MODEL = "gemini-3.1-flash-image-preview"  # Nano Banana 2 (編集対応)


def edit(input_path: Path, instruction: str) -> Path:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    src_image = Image.open(input_path)

    logger.info("Editing %s with %s ...", input_path.name, EDIT_MODEL)
    response = client.models.generate_content(
        model=EDIT_MODEL,
        contents=[instruction, src_image],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    image_data = None
    for p in response.candidates[0].content.parts:
        if hasattr(p, "inline_data") and p.inline_data and p.inline_data.data:
            image_data = p.inline_data.data
            break
    if not image_data:
        raise RuntimeError("No image in response")

    out_dir = PROJECT_ROOT / "tools" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 入力ファイルのプレフィックス（cover_ / episode_ など）を維持
    stem = input_path.stem
    prefix = stem.split("_")[0] if "_" in stem else "image"
    out_path = out_dir / f"{prefix}_{timestamp}.png"
    out_path.write_bytes(image_data)
    logger.info("Saved: %s (%d KB)", out_path, len(image_data) // 1024)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    p = edit(Path(sys.argv[1]), sys.argv[2])
    print(f"OPEN: {p}")
