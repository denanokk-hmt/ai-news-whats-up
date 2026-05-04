from __future__ import annotations

import logging
import os

import httpx

from src.config import today_jst

logger = logging.getLogger(__name__)


def _build_blocks(
    articles: list[dict],
    podcast_url: str = "",
    gdrive_url: str = "",
    feed_url: str = "",
) -> list[dict]:
    today = today_jst().strftime("%Y-%m-%d")
    weekday = ["月", "火", "水", "木", "金", "土", "日"][today_jst().weekday()]

    top_articles = sorted(
        articles,
        key=lambda a: a.get("importance", 0),
        reverse=True,
    )[:5]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🎙️ AI Daily What's up - {today}（{weekday}）",
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"記事数: *{len(articles)}件* | 注目度上位5件"},
            ],
        },
        {"type": "divider"},
    ]

    for i, a in enumerate(top_articles, 1):
        title = a.get("japanese_title", a.get("original_title", ""))
        url = a.get("url", "")
        source = a.get("source", "")
        genre = a.get("genre", "")
        stars = "⭐" * int(a.get("importance", 0))
        summary = a.get("summary_ja", "")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. <{url}|{title}>*\n"
                    f"`{genre}` {stars} | {source}\n"
                    f"> {summary}"
                ),
            },
        })

    blocks.append({"type": "divider"})

    action_elements = []
    if podcast_url:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "🎧 聴く（Podcast）"},
            "url": podcast_url,
            "style": "primary",
        })
    if gdrive_url:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "📄 詳細（GDrive）"},
            "url": gdrive_url,
        })
    if feed_url:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "🔗 RSSフィード"},
            "url": feed_url,
        })

    if action_elements:
        blocks.append({"type": "actions", "elements": action_elements})

    return blocks


def notify(
    articles: list[dict],
    podcast_url: str = "",
    gdrive_url: str = "",
    feed_url: str = "",
) -> bool:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping notification")
        return False

    blocks = _build_blocks(articles, podcast_url, gdrive_url, feed_url)
    payload = {
        "text": f"AI Daily What's up - {today_jst().strftime('%Y-%m-%d')}",
        "blocks": blocks,
    }

    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Sent Slack notification")
        return True
    except httpx.HTTPError as e:
        logger.error("Slack notification failed: %s", e)
        return False


def notify_failure(error_message: str) -> bool:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False

    today = today_jst().strftime("%Y-%m-%d %H:%M")
    payload = {
        "text": f"⚠️ AI Daily What's up - {today} 実行失敗",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"⚠️ 実行失敗 - {today}",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{error_message[:500]}```"},
            },
        ],
    }

    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
