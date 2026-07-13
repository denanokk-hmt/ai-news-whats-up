from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from src.config import JST, output_dir, today_jst
from src.retry import with_retry
from src import usage

logger = logging.getLogger(__name__)

# grounding の発火は確率的なので、空振りしたら Step A を最大この回数まで再試行する。
SEARCH_MAX_ATTEMPTS = 4

# 注意: このプロンプトは意図的に短く保つ。長大・規則過多にすると Gemini が
# google_search ツールを呼ばず学習データから作文する（grounding が 0 になり
# 古い/捏造ニュースを生む）。重複回避は downstream の dedup.filter_new が担う。
PROMPT_TEMPLATE = """Google検索で、{window_start_jst}〜{window_end_jst}（JST）に公開された国内外のAI・LLM・機械学習ニュースを幅広く探してください。
- 国内(ITmedia/GIGAZINE/日経/Publickey/CNET等)から7件以上、海外(TechCrunch/The Verge/Reuters/VentureBeat/Bloomberg等)から15件以上
- ジャンル分散(LLM/規制/資金調達/研究/製品/ハードウェア/ロボ/自動運転/医療/OSS/国内 等)
- {window_start_jst}より前や総括・まとめ記事は除外("after:{search_after}"活用)
- 各記事を1行で列挙: 日本語見出し｜原文タイトル｜メディア｜公開日(YYYY-MM-DD HH:MM)｜URL｜日本語要約
検索でヒットした実在記事のみ。合計25〜30件程度。公開日不明は「不明」と記載。JSONにしない。"""


STRUCTURE_TEMPLATE = """以下は Web 検索で収集した AI ニュースの調査メモです。
これを指定の JSON 配列へ**機械的に構造化**してください。

【絶対厳守】
- メモに書かれていない記事・日付・要約を**新たに作り出さないこと**。
- **各記事の "url" は、下の「実ソースURL一覧」から本文に最も一致するものを1つ選び、
  完全一致でコピーする**。一覧に対応が見当たらない記事は出力に含めない。
  URLをドメインだけに短縮したり、創作・改変してはならない。
- 公開日が「不明」のものは published_at を空文字 "" にする（推測で埋めない）。

## 実ソースURL一覧（"url" は必ずこの中から選ぶ）
{url_list}

## 調査メモ
{findings}

## 出力
以下の JSON 配列のみ。前後の説明文・コードブロック記号（```）は不要：

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
    """Step A: 検索を確実に発火させる短い自然文プロンプト。

    重複回避トピック等を注入して長大化すると google_search が呼ばれず作文される
    ため、あえて短く保つ。重複除去は main の dedup.filter_new が担当する。
    """
    window_start, window_end = _get_window()
    return PROMPT_TEMPLATE.format(
        window_start_jst=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end_jst=window_end.strftime("%Y-%m-%d %H:%M"),
        search_after=window_start.strftime("%Y-%m-%d"),
    )


def _build_structuring_prompt(findings: str, url_list: str) -> str:
    """Step B: 検索結果メモを JSON へ構造化するプロンプト（検索ツールは使わない）。

    url_list は解決済みの実ソースURL一覧。モデルの自己申告URL（ドメイン止まり・
    創作）を排し、各記事に実在の深リンクを割り当てさせるために渡す。
    """
    return STRUCTURE_TEMPLATE.format(findings=findings, url_list=url_list)


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

    raw = match.group()
    # strict=False で文字列値内の生改行・タブ等の制御文字を許容する
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        # それでも壊れている場合は文字列を破壊しない範囲で制御文字を除去して再試行
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
        return json.loads(cleaned, strict=False)


# 大手一次ソース・主要メディアの登録ドメイン。ここに無いドメインの記事は
# 除外はしないが importance を UNTRUSTED_IMPORTANCE_CAP に頭打ちする。
# （2026-07-07: zoombangla.com のフェイク「Gemini 3発表」記事が importance 5 で
# digest 先頭に載った事故への対策。検索グラウンディングは「実在する検索結果」
# しか保証せず、コンテンツファームの捏造記事は素通しになるため。）
TRUSTED_DOMAINS = {
    # AI ベンダー一次ソース
    "google.com", "blog.google", "deepmind.google", "openai.com",
    "anthropic.com", "microsoft.com", "apple.com", "meta.com",
    "nvidia.com", "amazon.com", "huggingface.co", "github.blog",
    "mistral.ai", "stability.ai", "x.ai",
    # 海外メディア
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "nytimes.com",
    "theguardian.com", "bbc.com", "cnbc.com", "axios.com", "time.com",
    "techcrunch.com", "theverge.com", "venturebeat.com", "wired.com",
    "arstechnica.com", "cnet.com", "forbes.com", "technologyreview.com",
    "theinformation.com", "semafor.com",
    # 国内メディア・一次ソース
    "itmedia.co.jp", "gigazine.net", "nikkei.com", "publickey1.jp",
    "impress.co.jp", "ascii.jp", "japantimes.co.jp", "nhk.or.jp",
    "asahi.com", "yomiuri.co.jp", "mainichi.jp", "prtimes.jp",
    "softbank.jp", "meti.go.jp", "nict.go.jp",
}

UNTRUSTED_IMPORTANCE_CAP = 3

# 末尾2ラベルでは登録ドメインを取り違える複合TLD（co.jp 等）は3ラベルで扱う
_MULTI_LABEL_TLDS = {
    "co.jp", "or.jp", "ne.jp", "go.jp", "ac.jp",
    "co.uk", "org.uk", "com.au", "co.kr", "com.br", "co.in",
}


def _registrable_domain(host: str) -> str:
    """ホスト名を登録ドメイン相当（例: jp.reuters.com -> reuters.com）に正規化。"""
    host = host.lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_LABEL_TLDS:
        return ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host


def _host_from(value: str) -> str | None:
    """URL またはベアドメイン文字列からホスト名を取り出す。判別不能なら None。"""
    if not value:
        return None
    v = value.strip()
    if "://" in v:
        try:
            netloc = urllib.parse.urlparse(v).netloc
        except ValueError:
            return None
        return netloc or None
    # グラウンディングの title は素のドメイン（"reuters.com"）であることが多い。
    # 空白を含む・ドットが無いものはページタイトル等とみなし採用しない。
    if " " in v or "." not in v:
        return None
    return v


def _grounding_domains(grounding_sources: list[dict]) -> set[str]:
    """グラウンディング結果から実在ソースの登録ドメイン集合を作る。"""
    domains: set[str] = set()
    for s in grounding_sources:
        for key in ("title", "url"):
            host = _host_from(s.get(key, ""))
            if not host:
                continue
            # Google 検索のリダイレクトホストは実ソースではないので除外
            if "vertexaisearch" in host or host.endswith("google.com"):
                continue
            dom = _registrable_domain(host)
            if dom:
                domains.add(dom)
    return domains


def _grounding_uris(grounding_sources: list[dict]) -> set[str]:
    """グラウンディングが返した生URI集合（多くは Google のリダイレクトURL）。"""
    return {
        (s.get("url") or "").strip()
        for s in grounding_sources
        if (s.get("url") or "").strip()
    }


# ページ本文から公開日時を拾うためのパターン。信頼度の高い順に試す。
# 属性順は媒体により逆転する（content が先に来る）ため両方向を用意する。
_PUBLISHED_AT_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+'
        r'content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
        r'property=["\']article:published_time["\']', re.IGNORECASE),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
]

# 公開日抽出のために読む本文の上限。メタタグは先頭付近にあるため十分。
_PAGE_READ_LIMIT = 300_000


def _extract_published_at(html_text: str) -> str | None:
    """HTML から公開日時（ISO 8601 文字列）を抽出。見つからなければ None。

    パース可能な日時のみ返す（_filter_by_date と同じ規則で解釈できることを保証）。
    """
    for pat in _PUBLISHED_AT_PATTERNS:
        m = pat.search(html_text)
        if not m:
            continue
        raw = m.group(1).strip()
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        return raw
    return None


def _resolve_redirect(
    client: httpx.Client, url: str
) -> tuple[str, str | None] | None:
    """1 本のリダイレクトURLを (実記事URL, ページ公開日時|None) へ解決。失敗時 None。

    公開日時はページの article:published_time / datePublished メタから拾う。
    モデルが「公開日不明」と申告した記事の日付をページ実測で補完し、収集
    ウィンドウ外の古い記事（コンテンツファームの焼き直し等）を機械的に落とす。
    """
    published_at = None
    try:
        r = client.get(url, follow_redirects=True)
        final = str(r.url)
        try:
            published_at = _extract_published_at(r.text[:_PAGE_READ_LIMIT])
        except Exception:
            pass  # 文字コード不明等。URL解決自体は成立している
    except Exception:
        # GET 拒否サーバ等は HEAD で URL 解決のみ再試行（公開日は諦める）
        try:
            r = client.head(url, follow_redirects=True)
            final = str(r.url)
        except Exception:
            return None
    if not final:
        return None
    host = _host_from(final) or ""
    # 解決しきれず Google 側に留まっているものは実ソースではないので捨てる
    if "vertexaisearch" in host or host.endswith("google.com"):
        return None
    return final, published_at


def _resolve_grounding_urls(
    grounding_sources: list[dict], deadline_s: float = 90.0
) -> tuple[dict[str, str], dict[str, str]]:
    """grounding のリダイレクトURI → 実記事URL の対応表と、
    実記事URL → ページ実測の公開日時 の対応表を作る。

    ネットワークを叩くため、1 本ごとに短いタイムアウトを課し、全体も
    deadline_s で打ち切る（過去の無限ハング事故対策）。解決できなかったものは
    表に載せず、呼び出し側で元のURLのまま残す。
    """
    mapping: dict[str, str] = {}
    date_map: dict[str, str] = {}
    start = time.monotonic()
    timeout = httpx.Timeout(6.0, connect=5.0)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ainews/1.0)"}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for s in grounding_sources:
            if time.monotonic() - start > deadline_s:
                logger.warning(
                    "Redirect resolution deadline (%.0fs) hit; resolved %d so far",
                    deadline_s, len(mapping),
                )
                break
            uri = (s.get("url") or "").strip()
            if not uri or uri in mapping:
                continue
            resolved = _resolve_redirect(client, uri)
            if resolved:
                real, published_at = resolved
                mapping[uri] = real
                if published_at:
                    date_map[real] = published_at
    logger.info("Resolved %d/%d grounding redirect URLs (%d with page dates)",
                len(mapping), len(grounding_sources), len(date_map))
    return mapping, date_map


def _fill_missing_dates(articles: list[dict], date_map: dict[str, str]) -> None:
    """published_at が空の記事に、ページ実測の公開日時を補完する（in-place）。

    モデルの「公開日不明」申告は date filter を素通りする（保留扱い）ため、
    ページから日付が取れた記事はここで埋めてウィンドウ判定の対象に載せる。
    """
    filled = 0
    for a in articles:
        if a.get("published_at"):
            continue
        page_date = date_map.get((a.get("url") or "").strip())
        if page_date:
            a["published_at"] = page_date
            filled += 1
            logger.info("Filled published_at from page meta: %s | %s",
                        page_date, a.get("japanese_title", "")[:50])
    if filled:
        logger.info("Filled %d missing published_at from page metadata", filled)


def _cap_importance_by_trust(articles: list[dict]) -> None:
    """信頼ドメイン外の記事の importance を頭打ちにする（in-place）。

    除外はしない（ニッチな良記事もあるため）。digest・台本は importance 降順で
    並ぶので、キャップにより無名ソースの記事がトップ扱いされるのを防ぐ。
    """
    capped = 0
    for a in articles:
        host = _host_from((a.get("url") or "").strip())
        dom = _registrable_domain(host) if host else None
        importance = a.get("importance")
        if dom in TRUSTED_DOMAINS:
            continue
        if isinstance(importance, int) and importance > UNTRUSTED_IMPORTANCE_CAP:
            a["importance"] = UNTRUSTED_IMPORTANCE_CAP
            capped += 1
            logger.info(
                "Capped importance %d -> %d (untrusted domain %s): %s",
                importance, UNTRUSTED_IMPORTANCE_CAP, dom,
                a.get("japanese_title", "")[:50],
            )
    if capped:
        logger.info("Importance capped for %d articles from untrusted domains",
                    capped)


def _cross_check_grounding(
    articles: list[dict], grounding_sources: list[dict]
) -> list[dict]:
    """検索でヒットした実ソースに紐づかない記事（捏造の疑い）を除外。

    grounding_chunks の URI は多くが vertexaisearch のリダイレクトURLで、実
    publisher ドメインは持たない。そのため照合は次の OR で行う:
      (1) 記事URLが grounding の返した URI そのもの（＝検索結果由来）
      (2) 記事URLの登録ドメインが、title 等から導けた実 publisher ドメインに一致
    どちらの手掛かりも作れない場合のみ、誤除去を避けて照合をスキップする。
    """
    domains = _grounding_domains(grounding_sources)
    uris = _grounding_uris(grounding_sources)
    if not domains and not uris:
        logger.warning(
            "No usable grounding evidence derived; skipping URL cross-check"
        )
        return articles

    kept: list[dict] = []
    dropped = 0
    for a in articles:
        url = (a.get("url") or "").strip()
        host = _host_from(url)
        dom = _registrable_domain(host) if host else None
        if (url and url in uris) or (dom and dom in domains):
            kept.append(a)
        else:
            dropped += 1
            logger.info(
                "Dropped (URL not grounded): %s | %s",
                url, a.get("japanese_title", "")[:50],
            )
    logger.info(
        "Grounding cross-check: %d -> %d (dropped %d ungrounded)",
        len(articles), len(kept), dropped,
    )
    return kept


def collect_news(model: str) -> tuple[list[dict], list[dict]]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in environment")

    # timeout は HTTP の「無通信」タイムアウト。長すぎると応答が細々と続く限り
    # 数時間ハングし得るため 3 分に短縮し、総時間は overall_deadline で縛る。
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=180_000),  # 3 分（無通信タイムアウト）
    )
    # === Step A: 検索（自然文出力でツールを確実に発火させる） ===
    # 「JSON配列のみ出力せよ」の指示があると google_search が呼ばれず、モデルが
    # 学習データから作文する（2026-06 の古い/捏造ニュース配信の真因）。よって
    # 検索は自然文で行い、構造化は後段（Step B）に分離する。
    #
    # さらに grounding の発火は確率的で、同じプロンプトでも検索されず 0 件になる
    # ことがある（＝作文モードに落ちる）。grounding が返るまで数回リトライし、
    # 全試行が空だったときだけ休載（abort）する。
    search_prompt = _build_prompt()
    findings = ""
    grounding_sources: list[dict] = []
    for attempt in range(1, SEARCH_MAX_ATTEMPTS + 1):
        logger.info(
            "Step A attempt %d/%d: searching with Gemini (%s) + Google Search...",
            attempt, SEARCH_MAX_ATTEMPTS, model,
        )
        search_resp = with_retry(
            client.models.generate_content,
            model=model,
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.3,
            ),
            overall_deadline=600,  # 全リトライ合計で最大 10 分。超過したら失敗通知へ
        )
        usage.record("collect_search", model, search_resp)

        attempt_sources: list[dict] = []
        if search_resp.candidates and search_resp.candidates[0].grounding_metadata:
            meta = search_resp.candidates[0].grounding_metadata
            for chunk in meta.grounding_chunks or []:
                if hasattr(chunk, "web") and chunk.web:
                    attempt_sources.append({
                        "title": chunk.web.title,
                        "url": chunk.web.uri,
                    })

        logger.info("Step A attempt %d grounding sources: %d",
                    attempt, len(attempt_sources))
        if attempt_sources and search_resp.text:
            findings = search_resp.text
            grounding_sources = attempt_sources
            break
        logger.warning(
            "Step A attempt %d produced no grounding; retrying", attempt
        )

    # 検索グラウンディングが一切得られなかった＝実検索が空振り/失敗し、モデルが
    # 学習データから「それっぽいニュース」を作文する状態。古い/捏造ニュースを
    # 流すよりは休載が正しいので、収集失敗として失敗通知に倒す。
    if not grounding_sources:
        raise RuntimeError(
            f"Google Search grounding returned no sources after "
            f"{SEARCH_MAX_ATTEMPTS} attempts; aborting to avoid publishing "
            f"hallucinated/old news."
        )

    # === Step B: 構造化（検索ツール無し。検索メモを捏造せず JSON へ変換するだけ） ===
    logger.info("Step B: structuring %d chars of findings into JSON...",
                len(findings))
    # grounding のURLは Google のリダイレクトURL。先に実記事URL（深リンク）へ解決し、
    # その一覧を Step B に渡して「urlは必ずこの一覧から選べ」と強制する。これにより
    # モデルの自己申告URL（ドメイン止まり・創作）を排除する。
    redirect_map, date_map = _resolve_grounding_urls(grounding_sources)
    url_lines: list[str] = []
    resolved_sources: list[dict] = []
    for s in grounding_sources:
        uri = (s.get("url") or "").strip()
        if not uri:
            continue
        real = redirect_map.get(uri, uri)  # 未解決はリダイレクトURLのまま（機能はする）
        title = (s.get("title") or "").strip()
        url_lines.append(f"- {title} => {real}" if title else f"- {real}")
        resolved_sources.append({"title": title, "url": real})
    url_list = "\n".join(url_lines) if url_lines else "(なし)"

    struct_resp = with_retry(
        client.models.generate_content,
        model=model,
        contents=_build_structuring_prompt(findings, url_list),
        config=types.GenerateContentConfig(temperature=0.2),
        overall_deadline=600,
    )
    usage.record("collect_structure", model, struct_resp)
    if not struct_resp.text:
        raise RuntimeError("Empty response from Gemini (structuring step)")

    articles = _extract_json(struct_resp.text)
    logger.info("Collected %d articles (raw)", len(articles))

    # モデルが「公開日不明」とした記事はページ実測の日付で補完してから
    # ウィンドウ判定にかける（2026-07-07 の zoombangla フェイク記事は
    # published_at 空欄で date filter を素通りした）。
    _fill_missing_dates(articles, date_map)

    articles = _filter_by_date(articles)
    logger.info("After date filter: %d articles", len(articles))

    # url は実ソースURL一覧（解決済み実URL）由来のはず。念のため実URL集合と実ドメインで
    # cross-check し、一覧に紐づかない記事（万一の創作）を除外する。
    before = len(articles)
    articles = _cross_check_grounding(articles, resolved_sources)
    if before > 0 and not articles:
        raise RuntimeError(
            "All collected articles failed the grounding cross-check "
            "(likely hallucinated); aborting to avoid publishing old/fake news."
        )

    # 信頼ドメイン外のソースは importance を頭打ちにし、digest/台本の
    # トップ扱いを防ぐ（除外はしない）。
    _cap_importance_by_trust(articles)

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
