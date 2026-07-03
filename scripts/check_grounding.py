"""Google 検索グラウンディングが実機能しているかを単独で検証する。

パイプライン全体を回さず、collect_news と同じ設定（モデル・GoogleSearch ツール・
temperature）で Gemini を 1 回だけ叩き、以下を切り分けて表示する:

  ① web_search_queries … モデルが実際に検索クエリを発行したか
  ② grounding_chunks   … 実在ソースが返ってきたか（0 なら＝作文の温床）
  ③ published_at       … 返答記事の自己申告日（本物か疑う材料）

APIキーは環境変数から読むだけで、一切表示しない。

使い方:
    python3 scripts/check_grounding.py
"""

from __future__ import annotations

import os
import sys

# src.config の import で load_dotenv(.env) が走り GEMINI_API_KEY が読み込まれる
from src.config import load_config  # noqa: E402
from src.collector import _build_prompt, _extract_json  # noqa: E402

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("NG: GEMINI_API_KEY が未設定です（.env を確認）")
        return 2

    config = load_config()
    model = config["gemini"]["collection_model"]
    prompt = _build_prompt()

    print(f"model = {model}")
    print("Gemini を GoogleSearch ツール付きで 1 回呼び出します...\n")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=180_000),
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )

    # --- ① / ② グラウンディングメタデータ ---
    queries: list[str] = []
    chunks: list[tuple[str, str]] = []
    if response.candidates and response.candidates[0].grounding_metadata:
        meta = response.candidates[0].grounding_metadata
        queries = list(meta.web_search_queries or [])
        for c in meta.grounding_chunks or []:
            if getattr(c, "web", None):
                chunks.append((c.web.title or "", c.web.uri or ""))

    print("=" * 60)
    print(f"① web_search_queries : {len(queries)} 件")
    for q in queries[:10]:
        print(f"    - {q}")
    print(f"② grounding_chunks   : {len(chunks)} 件")
    for title, uri in chunks[:10]:
        print(f"    - {title[:50]} | {uri[:60]}")

    # --- ③ 返答記事の published_at ---
    print("③ 返答記事の published_at:")
    try:
        articles = _extract_json(response.text or "")
        print(f"    articles = {len(articles)} 件")
        for a in articles[:10]:
            print(
                f"    - {a.get('published_at','(なし)')} | "
                f"{a.get('source','?')} | {a.get('japanese_title','')[:36]}"
            )
    except Exception as e:  # noqa: BLE001
        print(f"    JSON 抽出失敗: {e}")

    # --- 判定 ---
    print("=" * 60)
    if len(chunks) == 0:
        print("判定: ❌ grounding_chunks=0 → 実検索が成立していない。")
        print("      モデルは学習データから作文しており、古い/捏造ニュースの温床。")
        print("      → モデル/ツール設定側の問題。abort ガード導入前にここを直す必要あり。")
        return 1

    print("判定: ✅ grounding が返っている → API は正常。")
    print("      本番だけ失敗するなら環境要因（ネットワーク/キー権限/リージョン）を疑う。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
