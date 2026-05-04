"""声の組み合わせを3案比較するためのサンプル生成スクリプト。"""
from __future__ import annotations

import logging
import sys

from src.audio_generator import generate_audio
from src.config import PROJECT_ROOT, output_dir, today_jst

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-tts-preview"

SAMPLE_SCRIPT = """TAKU: おはようございます、AI What's Up Newsです！
MIO: 今日もAI業界の熱いニュースをお届けします。
TAKU: 早速ですが、OpenAIが1220億ドル調達というニュース、これマジですごいですよね。
MIO: ええっ、1220億ですか！？日本の国家予算レベルじゃないですか。
TAKU: そうなんです、もはやスタートアップの域を超えてますよね。
MIO: うわー、テック業界のスケール感が本当に変わってきましたね。"""

COMBOS = [
    ("A_Puck_Autonoe", [
        {"name": "TAKU", "role": "男性ホスト", "voice": "Puck"},
        {"name": "MIO", "role": "女性ホスト", "voice": "Autonoe"},
    ]),
    ("B_Sadachbia_Laomedeia", [
        {"name": "TAKU", "role": "男性ホスト", "voice": "Sadachbia"},
        {"name": "MIO", "role": "女性ホスト", "voice": "Laomedeia"},
    ]),
    ("C_Fenrir_Leda", [
        {"name": "TAKU", "role": "男性ホスト", "voice": "Fenrir"},
        {"name": "MIO", "role": "女性ホスト", "voice": "Leda"},
    ]),
]


def main():
    out_dir = PROJECT_ROOT / "tools" / "voice_samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    for label, speakers in COMBOS:
        logger.info("=== %s ===", label)
        try:
            mp3 = generate_audio(SAMPLE_SCRIPT, MODEL, speakers)
            target = out_dir / f"{label}.mp3"
            mp3.replace(target)
            logger.info("Saved: %s", target)
        except Exception as e:
            logger.error("Failed %s: %s", label, e)

    logger.info("All samples in: %s", out_dir)


if __name__ == "__main__":
    main()
