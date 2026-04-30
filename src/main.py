from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

PROMPT = """あなたはAIニュースキュレーターです。
Google検索を使って、今日の国内外のAI・人工知能・LLM・機械学習に関する最新ニュースを網羅的に収集してください。

以下の形式でMarkdownにまとめてください：

# AI News Digest - {date}

## 🌍 海外ニュース

### 1. [記事タイトル](URL)
**ソース**: メディア名 | **日付**: YYYY-MM-DD
> 2-3文の要約

（10件以上）

## 🇯🇵 国内ニュース

### 1. [記事タイトル](URL)
**ソース**: メディア名 | **日付**: YYYY-MM-DD
> 2-3文の要約

（5件以上）

## 📊 本日の注目トピック
- 最も重要なトレンドを3つ箇条書き

条件:
- 過去24時間以内のニュースを優先
- 企業動向、研究発表、規制・政策、製品リリース、資金調達を幅広くカバー
- URLは実在するものだけを記載
- 日本語で出力
"""


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def run_label() -> str:
    now = datetime.now(JST)
    period = "morning" if now.hour < 15 else "evening"
    return f"{now.strftime('%Y-%m-%d')}_{period}"


def fetch_and_summarize(model: str) -> tuple[str, list]:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    today = datetime.now(JST).strftime("%Y年%m月%d日")
    prompt = PROMPT.replace("{date}", today)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    sources = []
    if response.candidates and response.candidates[0].grounding_metadata:
        metadata = response.candidates[0].grounding_metadata
        if metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if hasattr(chunk, "web") and chunk.web:
                    sources.append({"title": chunk.web.title, "url": chunk.web.uri})

    return response.text, sources


def save_digest(content: str, label: str) -> Path:
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"{label}.md"
    path.write_text(content, encoding="utf-8")
    return path


def main():
    config = load_config()
    label = run_label()
    model = config.get("gemini", {}).get("model", "gemini-2.5-pro")

    logger.info("=== AI News Aggregator - %s ===", label)
    logger.info("Using model: %s with Google Search grounding", model)

    # Gemini + Google Search = 収集+要約を一発で実行
    logger.info("Fetching and summarizing AI news...")
    digest, sources = fetch_and_summarize(model)

    # ソース情報を追記
    if sources:
        digest += "\n\n## 参照元\n"
        for s in sources:
            digest += f"- [{s['title']}]({s['url']})\n"

    # ローカル保存
    path = save_digest(digest, label)
    logger.info("Digest saved to: %s", path)

    # プレビュー出力
    print("\n" + digest[:2000])
    if len(digest) > 2000:
        print(f"\n... (full digest: {path})")


if __name__ == "__main__":
    main()
