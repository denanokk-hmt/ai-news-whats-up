from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import sqlite_utils

from src.config import PROJECT_ROOT, today_jst

logger = logging.getLogger(__name__)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign",
    "utm_content", "utm_term", "fbclid", "gclid",
}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.lower().rstrip("/"))
    cleaned_query = {
        k: v for k, v in parse_qs(parsed.query).items()
        if k not in TRACKING_PARAMS
    }
    cleaned = parsed._replace(
        query=urlencode(cleaned_query, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def _url_hash(url: str) -> str:
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()[:16]


class Deduplicator:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite_utils.Database(str(path))
        if "seen_articles" not in self.db.table_names():
            self.db["seen_articles"].create({
                "url_hash": str,
                "url": str,
                "title": str,
                "source": str,
                "first_seen_at": str,
            }, pk="url_hash")

    def filter_new(self, articles: list[dict]) -> list[dict]:
        """既読でない記事のみ返す（DB は変更しない・重複URLは1件に正規化）。

        既読登録は配信成功後に commit_seen() で行う（遅延コミット）。
        後段（台本・音声・公開）で失敗しても記事が「消費」されず、
        単純再実行でリカバリ可能にするため、ここでは副作用を持たない。
        """
        new_articles: list[dict] = []
        seen_in_batch: set[str] = set()

        for article in articles:
            url = article.get("url", "")
            if not url:
                continue

            h = _url_hash(url)
            if h in seen_in_batch:
                continue

            existing = self.db["seen_articles"].count_where("url_hash = ?", [h])
            if existing > 0:
                continue

            seen_in_batch.add(h)
            new_articles.append(article)

        logger.info("Dedup: %d -> %d articles (%d duplicates removed)",
                    len(articles), len(new_articles),
                    len(articles) - len(new_articles))
        return new_articles

    def commit_seen(self, articles: list[dict]) -> int:
        """記事を既読として確定登録する（配信成功後に呼ぶ）。"""
        now_iso = today_jst().isoformat()
        committed = 0

        for article in articles:
            url = article.get("url", "")
            if not url:
                continue

            h = _url_hash(url)
            if self.db["seen_articles"].count_where("url_hash = ?", [h]) > 0:
                continue

            self.db["seen_articles"].insert({
                "url_hash": h,
                "url": url,
                "title": article.get("japanese_title") or article.get("original_title", ""),
                "source": article.get("source", ""),
                "first_seen_at": now_iso,
            })
            committed += 1

        logger.info("Dedup commit: %d articles marked seen", committed)
        return committed

    def purge_old(self, retention_days: int = 30):
        cutoff = (today_jst() - timedelta(days=retention_days)).isoformat()
        deleted = self.db.execute(
            "DELETE FROM seen_articles WHERE first_seen_at < ?",
            [cutoff],
        ).rowcount
        if deleted > 0:
            logger.info("Purged %d old records (>%d days)", deleted, retention_days)

    def stats(self) -> dict:
        total = self.db["seen_articles"].count
        return {"total_seen_articles": total}
