from __future__ import annotations

import logging
import sys
import traceback

from src.audio_generator import generate_audio
from src.collector import collect_news, save_articles
from src.config import PROJECT_ROOT, load_config, today_jst
from src.dedup import Deduplicator
from src.image_generator import (
    ensure_cover_exists,
    generate_episode_image,
)
from src.markdown_generator import generate_markdown, save_markdown
from src.notifiers.slack import notify, notify_failure
from src.script_generator import generate_script, save_script
from src.secure_logging import (
    configure_logging,
    install_sanitizing_root_handler,
    sanitize,
)
from src.storage.gdrive import get_authenticated_email, upload_episode
from src.storage.github_pages import publish_episode

configure_logging(logging.INFO)
install_sanitizing_root_handler()
logger = logging.getLogger(__name__)


def run():
    config = load_config()
    label = today_jst().strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("AI What's Up News - %s", label)
    logger.info("=" * 60)

    # Phase 1: 収集
    logger.info("[1/8] Collecting news...")
    articles, grounding_sources = collect_news(config["gemini"]["collection_model"])
    save_articles(articles, grounding_sources)

    # Phase 2: 重複排除
    logger.info("[2/8] Deduplicating...")
    dedup = Deduplicator(config["dedup"]["db_path"])
    dedup.purge_old(config["dedup"]["retention_days"])
    new_articles = dedup.filter_new(articles)
    if not new_articles:
        logger.warning("No new articles after dedup. Exiting.")
        return

    # Phase 3: 台本生成
    logger.info("[3/8] Generating script...")
    script = generate_script(new_articles, config["gemini"]["script_model"])
    save_script(script)

    # Phase 4: 音声生成
    logger.info("[4/8] Generating audio...")
    mp3_path = generate_audio(
        script,
        config["gemini"]["audio_model"],
        config["speakers"],
        tempo=config.get("audio", {}).get("tempo", 1.0),
        pitch_shift=config.get("audio", {}).get("pitch_shift", 1.0),
    )

    # Phase 5: エピソード画像生成
    logger.info("[5/8] Generating episode image...")
    cover_path = ensure_cover_exists(
        PROJECT_ROOT / config["image"]["cover_path"]
    )
    episode_image_path = None
    try:
        episode_image_path = generate_episode_image(
            articles=new_articles,
            cover_path=cover_path,
            instruction_template=config["image"]["episode"]["edit_instruction_template"],
            model=config["gemini"]["episode_image_model"],
        )
    except Exception as e:
        logger.error("Episode image generation failed: %s", e)

    # Phase 6: Markdownダイジェスト
    logger.info("[6/8] Generating markdown digest...")
    digest = generate_markdown(new_articles, script)
    digest_path = save_markdown(digest)

    # Phase 7: Google Drive
    logger.info("[7/8] Uploading to Google Drive...")
    gdrive_result = {}
    try:
        gdrive_result = upload_episode(
            mp3_path, digest_path, config["storage"]["gdrive"]["root_folder"],
        )
    except Exception as e:
        logger.error("GDrive upload failed: %s", e)

    # Phase 8: GitHub Pages
    logger.info("[8/8] Publishing to GitHub Pages...")
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
        )
    except Exception as e:
        logger.error("GitHub Pages publish failed: %s", e)

    # Slack通知
    logger.info("Sending Slack notification...")
    feed_url = f"{config['storage']['github']['pages_url']}/feed.xml"
    notify(
        articles=new_articles,
        podcast_url=podcast_url,
        gdrive_url=gdrive_result.get("digest_link", ""),
        feed_url=feed_url,
    )

    logger.info("=" * 60)
    logger.info("✅ Completed. Articles=%d Podcast=%s",
                len(new_articles), podcast_url or "N/A")
    logger.info("=" * 60)


def main():
    try:
        run()
    except Exception as e:
        logger.exception("Fatal error: %s", sanitize(str(e)))
        notify_failure(sanitize(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"))
        sys.exit(1)


if __name__ == "__main__":
    main()
