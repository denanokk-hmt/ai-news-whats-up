from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from src.config import output_dir, today_jst

logger = logging.getLogger(__name__)


def _star_rating(importance: int | None) -> str:
    if not importance:
        return ""
    return "⭐" * int(importance)


def _genre_emoji(genre: str) -> str:
    emojis = {
        "LLM": "🤖",
        "規制": "⚖️",
        "資金調達": "💰",
        "研究": "🔬",
        "製品": "🚀",
        "国内": "🇯🇵",
        "その他": "📰",
    }
    return emojis.get(genre, "📰")


def generate_markdown(
    articles: list[dict],
    script: str,
    podcast_link: str = "",
    gdrive_link: str = "",
) -> str:
    today = today_jst().strftime("%Y-%m-%d")
    weekday = ["月", "火", "水", "木", "金", "土", "日"][today_jst().weekday()]

    sorted_articles = sorted(
        articles,
        key=lambda a: a.get("importance", 0),
        reverse=True,
    )

    by_genre: dict[str, list[dict]] = defaultdict(list)
    for a in sorted_articles:
        genre = a.get("genre", "その他")
        by_genre[genre].append(a)

    lines = [
        f"# 🎙️ AI Daily What's up - {today}（{weekday}）",
        "",
        f"**配信日**: {today}　**記事数**: {len(articles)}件",
        "",
        "## 🎧 本日のエピソード",
        "",
    ]

    if podcast_link:
        lines.append(f"- [Spotifyで聴く]({podcast_link})")
    if gdrive_link:
        lines.append(f"- [Google Driveで聴く]({gdrive_link})")
    if not podcast_link and not gdrive_link:
        lines.append("（配信リンクは生成後に追記されます）")
    lines.append("")

    lines.extend([
        "## 📋 トピック一覧（ジャンル別）",
        "",
    ])

    genre_order = ["LLM", "研究", "製品", "資金調達", "規制", "国内", "その他"]
    sorted_genres = (
        [g for g in genre_order if g in by_genre]
        + [g for g in by_genre if g not in genre_order]
    )

    for genre in sorted_genres:
        emoji = _genre_emoji(genre)
        lines.append(f"### {emoji} {genre}")
        lines.append("")
        for a in by_genre[genre]:
            title = a.get("japanese_title", a.get("original_title", "（タイトル不明）"))
            url = a.get("url", "")
            source = a.get("source", "")
            stars = _star_rating(a.get("importance"))
            summary = a.get("summary_ja", "")

            lines.append(f"- [{title}]({url})")
            meta = []
            if source:
                meta.append(source)
            if stars:
                meta.append(stars)
            if meta:
                lines.append(f"  - {' | '.join(meta)}")
            if summary:
                lines.append(f"  - > {summary}")
        lines.append("")

    lines.extend([
        "## 🎬 台本全文",
        "",
        "```",
        script,
        "```",
        "",
    ])

    return "\n".join(lines)


def save_markdown(content: str) -> Path:
    out = output_dir()
    path = out / "digest.md"
    path.write_text(content, encoding="utf-8")
    logger.info("Saved digest to %s", path)
    return path
