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
from src.retry import with_retry

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """あなたはAIニュースキュレーターです。
Google検索を使って、**{window_start_jst}（JST）から {window_end_jst}（JST）までに公開された**
国内外のAI・人工知能・LLM・機械学習関連のニュースを網羅的に収集してください。

## 過去3日に取り上げた話題（重複回避のため避ける）
以下のトピック・企業×テーマの組み合わせは **既に取り上げ済み** なので、
**同じイベント・同じ発表の別ソース報道は除外**してください。新規進展がある場合のみ含めて可：

{recent_topics}

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
以下から最も該当するものを選択。複数該当の場合は上位優先：

1. **LLM**: ChatGPT/Claude/Gemini等の言語モデル本体の発表・更新
2. **規制**: 政府・規制機関のAI法規制・調査・声明
3. **資金調達**: AI企業の調達・IPO・買収・評価額
4. **研究**: 大学・研究機関の論文・新手法
5. **製品**: AIを組込んだエンドユーザー向け製品・SaaS
6. **ハードウェア**: AIチップ・GPU・データセンター・専用ハードウェア
7. **ロボティクス**: 物理ロボット・自律機械・ヒューマノイド
8. **自動運転**: 自動運転・モビリティAI
9. **医療**: 医療画像診断・創薬・ヘルスケアAI
10. **教育**: 教育・学習支援AI
11. **メディア**: コンテンツ生成・画像/音声/動画AI・エンタメ
12. **OSS**: オープンソースAI・モデル公開
13. **カンファレンス**: AI関連の発表会・イベント・受賞
14. **雇用影響**: AIによる職業・労働市場への影響
15. **量子**: 量子コンピューティング × AI
16. **国内**: 上記に該当しない日本企業・日本政府独自の発表
17. **その他**: それ以外

**ジャンルの偏りを避け、毎日5ジャンル以上をカバー**すること。

## 件数ターゲット
- **総数 25〜30件**（重複回避を優先しつつ）
- 国内ソース（ITmedia / 日経XTECH / 日経クロステック / GIGAZINE / ASCII / Publickey / ZDNET Japan / Impress Watch / TechCrunch Japan / CNET Japan / マイナビニュース / Ledge.ai / AIsmiley / AINOW）から **最低7件**
- 海外ソース（VentureBeat / TechCrunch / The Verge / MIT Tech Review / Ars Technica / Wired / Bloomberg / Reuters / FT等）から **最低15件**

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


def _load_recent_topics(days: int = 3) -> str:
    """過去N日分の articles.json からタイトル一覧を取得（重複回避用）。"""
    from src.config import PROJECT_ROOT
    output_root = PROJECT_ROOT / "output"
    if not output_root.exists():
        return "（履歴なし）"
    today = today_jst()
    lines = []
    for i in range(1, days + 1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        articles_path = output_root / d / "articles.json"
        if not articles_path.exists():
            continue
        try:
            data = json.loads(articles_path.read_text(encoding="utf-8"))
            titles = [a.get("japanese_title", "") for a in data.get("articles", [])]
            if titles:
                lines.append(f"【{d}】")
                for t in titles[:30]:
                    if t:
                        lines.append(f"  - {t}")
        except Exception:
            continue
    return "\n".join(lines) if lines else "（履歴なし）"


def _build_prompt() -> str:
    window_start, window_end = _get_window()
    return PROMPT_TEMPLATE.format(
        window_start_jst=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end_jst=window_end.strftime("%Y-%m-%d %H:%M"),
        search_after=window_start.strftime("%Y-%m-%d"),
        recent_topics=_load_recent_topics(days=3),
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
    response = with_retry(
        client.models.generate_content,
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
