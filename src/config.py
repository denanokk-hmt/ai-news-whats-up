from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

load_dotenv(PROJECT_ROOT / ".env")

# import時に自動的にロガー抑制（どのモジュールから走っても効く）
for _noisy in [
    "httpx", "httpcore", "urllib3", "requests",
    "googleapiclient.discovery_cache", "googleapiclient.discovery",
    "google_genai", "google.auth",
]:
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def today_jst() -> datetime:
    return datetime.now(JST)


def output_dir(date: datetime | None = None) -> Path:
    d = date or today_jst()
    path = PROJECT_ROOT / "output" / d.strftime("%Y-%m-%d")
    path.mkdir(parents=True, exist_ok=True)
    return path
