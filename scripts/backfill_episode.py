"""成果物が残っていない失敗日を、現在のニュースで埋め合わせ生成・公開する。

6/10・12・14・15 は収集段階でハングし script.txt も articles.json も無いため、
recover_episode.py（既存成果物の再利用）は使えない。本スクリプトは各日付について
新規にフル収集し、エピソードを生成・公開する。

復元不可（当時のニュースは収集ウィンドウを過ぎている）であることを前提に、
- 当日扱いの日付固定（today_jst を差し替え）
- dedup は介さない（過去の失敗で DB は汚れていないが、埋め合わせ各本を空にしないため）
で動かす。複数日を1プロセスで順次処理し、collector の「過去N日トピック回避」が
先に生成した日の articles.json を参照して内容を分散させる。

使い方:
    .venv/bin/python -m scripts.backfill_episode 2026-06-10 2026-06-12 2026-06-14 2026-06-15
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from src.config import JST, PROJECT_ROOT, load_config
import src.config as config_mod


def _pin_date(target: datetime) -> None:
    def fixed_today_jst() -> datetime:
        return target

    config_mod.today_jst = fixed_today_jst
    for name, module in list(sys.modules.items()):
        if not name.startswith("src."):
            continue
        if getattr(module, "today_jst", None) is not None:
            setattr(module, "today_jst", fixed_today_jst)


def _run_one(label: str, logger: logging.Logger) -> None:
    from src.audio_generator import generate_audio
    from src.collector import collect_news, save_articles
    from src.image_generator import ensure_cover_exists, generate_episode_image
    from src.markdown_generator import generate_markdown, save_markdown
    from src.netcheck import wait_for_network
    from src.notifiers.slack import notify
    from src.script_generator import generate_script, save_script
    from src.storage.gdrive import get_authenticated_email, upload_episode
    from src.storage.github_pages import publish_episode

    target = datetime.strptime(label, "%Y-%m-%d").replace(hour=7, minute=0, tzinfo=JST)
    _pin_date(target)
    config = load_config()

    logger.info("=" * 60)
    logger.info("BACKFILL %s", label)
    logger.info("=" * 60)

    wait_for_network()

    logger.info("[1/7] Collecting news...")
    articles, grounding_sources = collect_news(config["gemini"]["collection_model"])
    save_articles(articles, grounding_sources)
    if not articles:
        logger.error("No articles collected for %s; skipping", label)
        return

    logger.info("[2/7] Generating script...")
    script = generate_script(articles, config["gemini"]["script_model"])
    save_script(script)

    logger.info("[3/7] Generating audio...")
    mp3_path = generate_audio(
        script,
        config["gemini"]["audio_model"],
        config["speakers"],
        tempo=config.get("audio", {}).get("tempo", 1.0),
        pitch_shift=config.get("audio", {}).get("pitch_shift", 1.0),
        chunk_lines=config.get("audio", {}).get("chunk_lines", 10),
        bgm=config.get("audio", {}).get("bgm"),
    )

    logger.info("[4/7] Generating episode image...")
    cover_path = ensure_cover_exists(PROJECT_ROOT / config["image"]["cover_path"])
    episode_image_path = None
    try:
        episode_image_path = generate_episode_image(
            articles=articles,
            cover_path=cover_path,
            instruction_template=config["image"]["episode"]["edit_instruction_template"],
            model=config["gemini"]["episode_image_model"],
        )
    except Exception as e:
        logger.error("Episode image generation failed: %s", e)

    logger.info("[5/7] Generating markdown digest...")
    digest = generate_markdown(articles, script)
    digest_path = save_markdown(digest)

    logger.info("[6/7] Uploading to Google Drive...")
    gdrive_result = {}
    try:
        gdrive_result = upload_episode(
            mp3_path, digest_path, config["storage"]["gdrive"]["root_folder"],
        )
    except Exception as e:
        logger.error("GDrive upload failed: %s", e)

    logger.info("[7/7] Publishing to GitHub Pages...")
    podcast_url = ""
    try:
        owner_email = get_authenticated_email()
        podcast_url = publish_episode(
            mp3_source=mp3_path,
            cover_source=cover_path,
            episode_image_source=episode_image_path,
            podcast_meta=config["podcast"],
            repo=config["storage"]["github"]["repo"],
            branch=config["storage"]["github"]["branch"],
            pages_url=config["storage"]["github"]["pages_url"],
            owner_email=owner_email,
            articles=articles,
        )
    except Exception as e:
        logger.error("GitHub Pages publish failed: %s", e)

    feed_url = f"{config['storage']['github']['pages_url']}/feed.xml"
    notify(
        articles=articles,
        podcast_url=podcast_url,
        gdrive_url=gdrive_result.get("digest_link", ""),
        feed_url=feed_url,
    )
    logger.info("✅ Backfilled %s Podcast=%s", label, podcast_url or "N/A")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.backfill_episode YYYY-MM-DD [YYYY-MM-DD ...]",
              file=sys.stderr)
        sys.exit(2)

    from src.secure_logging import configure_logging, install_sanitizing_root_handler
    configure_logging(logging.INFO)
    install_sanitizing_root_handler()
    logger = logging.getLogger("backfill")

    for label in sys.argv[1:]:
        try:
            _run_one(label, logger)
        except Exception as e:
            logger.exception("Backfill failed for %s: %s", label, e)


if __name__ == "__main__":
    main()
