from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from google import genai
from google.genai import types

from src.config import output_dir, today_jst
from src.retry import with_retry

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """あなたはポッドキャスト「AI What's Up News」の台本作家です。
以下のニュースを元に、男性ホスト「TAKU」と女性ホスト「MIO」による**明るく活発で親しみやすい**対話形式の台本を作成してください。

## 番組情報
- 番組名: AI What's Up News
- 配信日: {date}
- ホスト: TAKU（男性）と MIO（女性）の2名（対等な関係、仲の良い友人同士のテンション）

## 構成要件
1. オープニング: 「おはようございます、AI What's Up Newsです」で始める
2. 本編: 重要度の高い記事から順に紹介、明るく活発な対話
3. クロージング: 「それではまた明日、よい一日を」で締める

## 掛け合いのスタイル（最重要）
- **必ず敬語（です・ます調）を維持**: タメ口・崩れた語尾（「〜だよね」「〜じゃん」「〜なんだよねー」「〜だよなー」等）は絶対禁止
- **感嘆語にバリエーション**: 「うわ〜」「へぇ〜」「マジですか」「ええっ」「すごっ」「やばいですね」「驚きですね」「ええ」「なるほど」等を多用し、ワンパターン化を避ける
- **個人的感想・本音**: ホストが時々「これ聞いた瞬間ちょっと震えました」「個人的には◯◯派ですね」のような主観・本音を挟む（**敬語のまま**）
- **日常的な例え**: 専門概念は身近な例えで説明する。例「ピークデータ＝お菓子の最後の一袋」「合成データ＝コピーのコピー」「IPO延期＝発表会のリスケ」など
- **双方向の発見**: 一方が説明してもう一方が質問する形を避け、両者が一緒に驚いたり考えたりする
- **適度な軽口・ユーモア**: 真面目過ぎず、時々茶目っ気のある軽い冗談を挟む（敬語の範囲で）
- **テンポ良く**: 短い発言を交互にポンポン繰り出す箇所を作る（特に驚きの場面）

## 男性ホスト TAKU の話し方（厳守）
- 必ず標準的な敬語のみを使う
- 推奨語尾: 「〜です」「〜ですね」「〜ですよ」「〜でしょうか」「〜ます」「〜ました」「〜だと思います」
- **絶対禁止の語尾（一度でも使ったらNG）**:
  - 「〜だよね」「〜だよなー」「〜なんだよ」「〜なんだよねー」
  - 「〜よね」「〜よねー」（語尾を伸ばすのは禁止、「〜ね」で止める）
  - 「〜じゃない？」「〜じゃん」「〜だな」「〜さ」
  - 「〜してて」「〜られてて」「〜ばかりで」のような中途半端な接続は避け、文末は明確に
  - 「〜みたい」（→「〜のようです」「〜だそうです」に置換）
- 語尾を伸ばさない（「ね」「よ」「な」を「ねー」「よー」「なー」と伸ばさない）

## 女性ホスト MIO の話し方（厳守）
- 明るく親しみやすい敬語のみ
- 推奨語尾: 「〜です」「〜ですね」「〜なんですよ」「〜でしょうか」「〜ますよね」
- **絶対禁止**:
  - 「〜よねー」「〜だよねー」「〜じゃない？」「〜じゃん」
  - 語尾を伸ばす表現全般

## フィラー（つなぎ語）の禁止
- **絶対禁止**: 「えー」「えーと」「えっとー」「あのー」「うーん」「まあ」「えー〇〇ですかー？」のような**間延びしたフィラー**
- 文の冒頭や途中に「えー、」「えーっと、」を入れるのは厳禁
- 自然な感嘆（「ええっ」「うわっ」等の短い驚き表現）は可、ただし「えー」と長く伸ばすのはNG

## 出力前の自己チェック（必須）
出力前に必ず全行を再読し、上記の禁止語尾・フィラーが一つでも含まれていれば書き直すこと。

## 文体・分量
- 全体で 3500〜5500字（音声化すると約 8〜13分）
- TAKUとMIOが交互に発言、発言量は均等に

## 出力形式
- 1行1発言、必ず以下の形式：
  TAKU: 発言内容
  MIO: 発言内容
- 上記形式以外（地の文・タイトル・ト書き等）は一切含めない
- 改行で区切る

## ニュース紹介時のルール
- 各ニュースを紹介するとき、**必ず公開日（YYYY年M月D日）に言及する**こと
- 例: 「次は5月3日に発表されたニュースで〜」「5月4日付の報道によると〜」「昨日、5月3日のニュースですが〜」
- 同じ日付が連続する場合は省略可（自然な流れを優先）

## 紹介すべきニュース
重要度の高い順に、以下から重要なものを選んで紹介してください：

{articles_text}

## 注意
- 全記事に触れる必要はない（重要度4以上を中心に）
- ジャンルが偏らないよう調整
- URLや出典を読み上げない（音声向きでないため）
- 暗い・ヒソヒソした話し方にならないよう、明るく前向きなテンションを保つ

それでは台本を出力してください。
"""


def _format_articles(articles: list[dict]) -> str:
    sorted_articles = sorted(
        articles,
        key=lambda a: a.get("importance", 0),
        reverse=True,
    )
    lines = []
    for i, a in enumerate(sorted_articles, 1):
        # 公開日を分かりやすい形式（YYYY年M月D日）に整形
        pub = a.get("published_at", "")
        date_str = ""
        if pub:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y年%-m月%-d日")
            except Exception:
                date_str = pub[:10]
        lines.append(
            f"[{i}] 【{a.get('genre', '?')}|重要度{a.get('importance', '?')}|公開日:{date_str}】 "
            f"{a.get('japanese_title', '')}\n"
            f"    出典: {a.get('source', '')}\n"
            f"    要約: {a.get('summary_ja', '')}"
        )
    return "\n\n".join(lines)


def _validate_script(script: str) -> tuple[bool, str]:
    lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
    if not lines:
        return False, "Empty script"

    valid_lines = [l for l in lines if l.startswith(("TAKU:", "MIO:"))]
    if len(valid_lines) < len(lines) * 0.9:
        return False, f"Only {len(valid_lines)}/{len(lines)} lines have TAKU:/MIO: prefix"

    char_count = sum(len(l.split(":", 1)[1].strip()) for l in valid_lines)
    if char_count < 2500:
        return False, f"Too short: {char_count} chars (min 2500)"
    if char_count > 7000:
        return False, f"Too long: {char_count} chars (max 7000)"

    taku_count = sum(1 for l in valid_lines if l.startswith("TAKU:"))
    mio_count = sum(1 for l in valid_lines if l.startswith("MIO:"))
    if taku_count == 0 or mio_count == 0:
        return False, f"Imbalanced: TAKU={taku_count}, MIO={mio_count}"

    return True, f"OK (TAKU={taku_count}, MIO={mio_count}, chars={char_count})"


def generate_script(articles: list[dict], model: str) -> str:
    if not articles:
        raise ValueError("No articles provided")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    today = today_jst().strftime("%Y年%m月%d日")
    prompt = PROMPT_TEMPLATE.format(
        date=today,
        articles_text=_format_articles(articles),
    )

    logger.info("Generating script with %s for %d articles...", model, len(articles))
    response = with_retry(
        client.models.generate_content,
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7),
    )

    if not response.text:
        raise RuntimeError("Empty response from Gemini")

    script = response.text.strip()
    is_valid, msg = _validate_script(script)
    if not is_valid:
        logger.warning("Script validation: %s", msg)
    else:
        logger.info("Script validation: %s", msg)

    return script


def save_script(script: str) -> Path:
    out = output_dir()
    path = out / "script.txt"
    path.write_text(script, encoding="utf-8")
    logger.info("Saved script to %s", path)
    return path
