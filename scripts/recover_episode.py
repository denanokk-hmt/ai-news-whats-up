"""失敗したエピソードを既存の script.txt / articles.json から復旧して再生成・公開する。

通常パイプライン（src/main.py）は today_jst() に依存して日付を決めるため、
過去日を対象にするには各モジュールの today_jst を固定値へ差し替える。
収集・台本は再実行せず、保存済み成果物を再利用する（dedup DB を汚さない）。

使い方:
    .venv/bin/python -m scripts.recover_episode 2026-06-08
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

from src.config import JST, PROJECT_ROOT, load_config
import src.config as config_mod


def _pin_date(target: datetime) -> None:
    """today_jst を import 済みの全モジュールで固定値に差し替える。"""
    def fixed_today_jst() -> datetime:
        return target

    config_mod.today_jst = fixed_today_jst
    # `from src.config import today_jst` で取り込んだモジュールも個別に差し替える
    for name, module in list(sys.modules.items()):
        if not name.startswith("src."):
            continue
        if getattr(module, "today_jst", None) is not None:
            setattr(module, "today_jst", fixed_today_jst)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m scripts.recover_episode YYYY-MM-DD", file=sys.stderr)
        sys.exit(2)

    label = sys.argv[1]
    target = datetime.strptime(label, "%Y-%m-%d").replace(hour=7, minute=0, tzinfo=JST)

    # まず全モジュールを import させてから today_jst を差し替える
    from src import audio_generator, image_generator, markdown_generator  # noqa: F401
    from src.audio_generator import generate_audio
    from src.image_generator import ensure_cover_exists, generate_episode_image
    from src.markdown_generator import generate_markdown, save_markdown
    from src.notifiers.slack import notify
    from src.secure_logging import configure_logging, install_sanitizing_root_handler
    from src.storage.gdrive import get_authenticated_email, upload_episode
    from src.storage.github_pages import publish_episode

    configure_logging(logging.INFO)
    install_sanitizing_root_handler()
    logger = logging.getLogger("recover")

    _pin_date(target)

    out = PROJECT_ROOT / "output" / label
    script_path = out / "script.txt"
    articles_path = out / "articles.json"
    if not script_path.exists() or not articles_path.exists():
        logger.error("Missing script.txt or articles.json under %s", out)
        sys.exit(1)

    script = script_path.read_text(encoding="utf-8")
    payload = json.loads(articles_path.read_text(encoding="utf-8"))
    articles = payload["articles"]

    config = load_config()
    logger.info("=" * 60)
    logger.info("RECOVER episode %s (articles=%d)", label, len(articles))
    logger.info("=" * 60)

    # Phase 4: 音声
    logger.info("[1/5] Generating audio...")
    mp3_path = generate_audio(
        script,
        config["gemini"]["audio_model"],
        config["speakers"],
        tempo=config.get("audio", {}).get("tempo", 1.0),
        pitch_shift=config.get("audio", {}).get("pitch_shift", 1.0),
        chunk_lines=config.get("audio", {}).get("chunk_lines", 10),
        bgm=config.get("audio", {}).get("bgm"),
    )

    # Phase 5: 画像
    logger.info("[2/5] Generating episode image...")
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

    # Phase 6: Markdown
    logger.info("[3/5] Generating markdown digest...")
    digest = generate_markdown(articles, script)
    digest_path = save_markdown(digest)

    # Phase 7: Google Drive
    logger.info("[4/5] Uploading to Google Drive...")
    gdrive_result = {}
    try:
        gdrive_result = upload_episode(
            mp3_path, digest_path, config["storage"]["gdrive"]["root_folder"],
        )
    except Exception as e:
        logger.error("GDrive upload failed: %s", e)

    # Phase 8: GitHub Pages
    logger.info("[5/5] Publishing to GitHub Pages...")
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

    logger.info("Sending Slack notification...")
    feed_url = f"{config['storage']['github']['pages_url']}/feed.xml"
    notify(
        articles=articles,
        podcast_url=podcast_url,
        gdrive_url=gdrive_result.get("digest_link", ""),
        feed_url=feed_url,
    )

    logger.info("=" * 60)
    logger.info("✅ Recovered %s Podcast=%s", label, podcast_url or "N/A")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
