from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from google import genai
from google.genai import types

from src.config import JST, output_dir, today_jst

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """あなたはAIニュースキュレーターです。
Google検索を使って、**{window_start_jst}（JST）から {window_end_jst}（JST）までに公開された**
国内外のAI・人工知能・LLM・機械学習関連のニュースを網羅的に収集してください。

【絶対遵守】時間範囲：
- **{window_start_jst} より前に公開された記事は絶対に含めないこと**
- 「最近のトピック」「過去のまとめ」「総括」「年間レビュー」記事は除外
- 検索時は "after:{search_after}" を使うなど、明示的に新しい記事を検索すること
- 上記範囲に該当する記事が見つからない場合、無理に古い記事で埋めず件数を減らすこと

要件:
- 海外記事はタイトルと要約を日本語に翻訳
- 重要度を1-5で採点（5が最重要）
- 企業動向、研究発表、規制・政策、製品リリース、資金調達を幅広くカバー
- URLは実在するものだけを記載
- **published_at は ISO 8601 形式で、必ず実際の公開日時を記載**

## ジャンル判定ルール（厳守）
以下の優先順位で判定してください。複数該当する場合は上位を優先：

1. **LLM**: ChatGPT / GPT-5 / Claude / Gemini / Llama / Mistral 等の **大規模言語モデル本体・派生モデル** に関するニュース。新モデル発表・性能向上・ベンチマーク・モデルアップデート・新機能（コンテキスト拡張、推論強化等）。**注意**: 「Claude が機能X追加」のような LLM のアップデートは「製品」ではなく **必ず LLM** に分類すること。
2. **規制**: 政府・規制機関（米EU日本等）の AI に関する法律・規制・声明・調査・議会動向
3. **資金調達**: AI企業の調達ラウンド、IPO、買収、評価額発表
4. **研究**: 大学・研究機関の論文発表・新手法・学術的ブレイクスルー（モデル本体ではない）
5. **製品**: AI機能を組み込んだエンドユーザー向け製品・SaaSサービス（LLM本体は含まない）
6. **国内**: 上記に当てはまらない、日本企業・日本政府・日本のスタートアップによる発表
7. **その他**: 上記に当てはまらないもの

## 国内ニュースの最低件数（厳守）
- **国内ソースから最低5件、可能なら8件以上**
- 日本のソース例: ITmedia / 日経XTECH / 日経クロステック / GIGAZINE / ASCII / Publickey / ZDNET Japan / Impress Watch / TechCrunch Japan / CNET Japan / マイナビニュース / Ledge.ai / AIsmiley / AINOW
- 国内ニュースが見つからない場合は、国内企業の海外向け発表を国内ソース扱いで含めても可
- 海外ソース（VentureBeat / TechCrunch / The Verge / MIT Tech Review / Ars Technica等）から最低10件

出力は以下のJSON配列のみ。前後の説明文・コードブロック記号（```）は不要：

[
  {{
    "url": "https://...",
    "original_title": "原文タイトル",
    "japanese_title": "日本語タイトル（原文が日本語ならそのまま）",
    "source": "メディア名（VentureBeat / ITmedia 等）",
    "published_at": "2026-04-28T12:00:00+09:00",
    "summary_ja": "2-3文の日本語要約",
    "genre": "LLM",
    "importance": 5,
    "is_japanese_source": false
  }}
]
"""


def _get_window() -> tuple[datetime, datetime]:
    """収集対象の時間ウィンドウを返す（JST）。"""
    now = today_jst()
    window_end = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        window_end = window_end - timedelta(days=1)
    window_start = window_end - timedelta(hours=24)
    return window_start, window_end


def _build_prompt() -> str:
    window_start, window_end = _get_window()
    return PROMPT_TEMPLATE.format(
        window_start_jst=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end_jst=window_end.strftime("%Y-%m-%d %H:%M"),
        search_after=window_start.strftime("%Y-%m-%d"),
    )


def _filter_by_date(articles: list[dict]) -> list[dict]:
    """published_at が時間ウィンドウから外れる記事を除外。"""
    window_start, window_end = _get_window()
    filtered = []
    excluded = 0
    for a in articles:
        pub_str = a.get("published_at")
        if not pub_str:
            # 日付不明のものは保留扱い（弾かない）
            filtered.append(a)
            continue
        try:
            pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=JST)
            if pub_dt < window_start or pub_dt > window_end + timedelta(hours=1):
                excluded += 1
                logger.info("Excluded (out of window): %s | %s",
                            pub_str, a.get("japanese_title", "")[:50])
                continue
        except (ValueError, TypeError):
            pass
        filtered.append(a)

    if excluded > 0:
        logger.info("Date filter: %d -> %d (excluded %d old articles)",
                    len(articles), len(filtered), excluded)
    return filtered


def _extract_json(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in response")

    return json.loads(match.group())


def collect_news(model: str) -> list[dict]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in environment")

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt()

    logger.info("Calling Gemini (%s) with Google Search grounding...", model)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )

    if not response.text:
        raise RuntimeError("Empty response from Gemini")

    articles = _extract_json(response.text)
    logger.info("Collected %d articles (raw)", len(articles))

    articles = _filter_by_date(articles)
    logger.info("After date filter: %d articles", len(articles))

    grounding_sources = []
    if response.candidates and response.candidates[0].grounding_metadata:
        meta = response.candidates[0].grounding_metadata
        if meta.grounding_chunks:
            for chunk in meta.grounding_chunks:
                if hasattr(chunk, "web") and chunk.web:
                    grounding_sources.append({
                        "title": chunk.web.title,
                        "url": chunk.web.uri,
                    })

    return articles, grounding_sources


def save_articles(articles: list[dict], grounding_sources: list[dict]) -> Path:
    out = output_dir()
    path = out / "articles.json"
    payload = {
        "collected_at": today_jst().isoformat(),
        "article_count": len(articles),
        "articles": articles,
        "grounding_sources": grounding_sources,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved articles to %s", path)
    return path
