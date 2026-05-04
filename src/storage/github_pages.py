from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import re
from datetime import datetime
from pathlib import Path

from feedgen.feed import FeedGenerator

from src.config import PROJECT_ROOT, today_jst

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"STDERR: {result.stderr[-500:]}"
        )
    return result.stdout


def _clone_gh_pages(repo: str, branch: str, target: Path) -> None:
    _run(["git", "clone", "--branch", branch, "--single-branch",
          f"git@github.com:{repo}.git", str(target)],
         cwd=PROJECT_ROOT)


def _build_feed(
    podcast_meta: dict,
    pages_url: str,
    episodes_dir: Path,
    images_dir: Path,
    cover_url: str,
    owner_email: str | None,
    episode_titles: dict[str, str] | None = None,
) -> str:
    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(podcast_meta["title"])
    fg.description(podcast_meta["description"])
    fg.link(href=pages_url, rel="alternate")
    fg.link(href=f"{pages_url}/feed.xml", rel="self")
    fg.language(podcast_meta["language"])
    fg.author({"name": podcast_meta["author"]})
    fg.image(cover_url)

    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_author(podcast_meta["author"])
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_summary(podcast_meta["description"])
    fg.podcast.itunes_image(cover_url)

    if owner_email:
        fg.podcast.itunes_owner(name=podcast_meta["author"], email=owner_email)

    episode_titles = episode_titles or {}
    mp3_files = sorted(
        episodes_dir.glob("*.mp3"),
        key=lambda p: p.stem,
        reverse=True,
    )

    for mp3 in mp3_files:
        # 先頭のYYYY-MM-DDだけ抽出（バージョン付き 2026-05-04-v2.mp3 等にも対応）
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", mp3.stem)
        if not m:
            continue
        date_str = m.group(1)
        try:
            pub_date = datetime.strptime(date_str, "%Y-%m-%d")
            pub_date = pub_date.replace(hour=7, minute=0, tzinfo=today_jst().tzinfo)
        except ValueError:
            continue

        fe = fg.add_entry()
        fe.id(f"{pages_url}/episodes/{mp3.name}")
        title = episode_titles.get(date_str, f"{date_str} AIニュース")
        fe.title(title)
        fe.description(f"{date_str} の国内外AIニュースをお届けします")
        fe.pubDate(pub_date)
        fe.enclosure(
            f"{pages_url}/episodes/{mp3.name}",
            str(mp3.stat().st_size),
            "audio/mpeg",
        )

        # エピソード画像を探す（優先1: mp3と同名 → 優先2: 日付部分のみ）
        mp3_stem = mp3.stem  # 例: "2026-05-04-r2"
        candidates = [mp3_stem, date_str]  # 完全一致 → 日付fallback
        found = False
        for stem in candidates:
            for ext in [".jpg", ".png"]:
                ep_image = images_dir / f"{stem}{ext}"
                if ep_image.exists():
                    fe.podcast.itunes_image(f"{pages_url}/episode_images/{stem}{ext}")
                    found = True
                    break
            if found:
                break

    return fg.rss_str(pretty=True).decode("utf-8")


def _next_versioned_filename(directory: Path, date: str, ext: str) -> str:
    """同日に既存ファイルがあればバージョン付きの新ファイル名を返す。

    例: 2026-05-04.mp3 が既存 → 2026-05-04-r2.mp3
        2026-05-04-r2.mp3 も既存 → 2026-05-04-r3.mp3
    """
    base = directory / f"{date}{ext}"
    if not base.exists():
        return f"{date}{ext}"
    # 既存ファイル一覧から世代番号を判定
    n = 2
    while (directory / f"{date}-r{n}{ext}").exists():
        n += 1
    return f"{date}-r{n}{ext}"


def _cleanup_old_versions(directory: Path, date: str, ext: str, keep: str) -> int:
    """指定日付の古いバージョンを削除（最新の keep ファイルだけ残す）。"""
    removed = 0
    for f in directory.glob(f"{date}*{ext}"):
        if f.name != keep:
            f.unlink()
            removed += 1
    return removed


def publish_episode(
    mp3_source: Path,
    cover_source: Path,
    episode_image_source: Path | None,
    podcast_meta: dict,
    repo: str,
    branch: str,
    pages_url: str,
    owner_email: str | None,
) -> str:
    today = today_jst().strftime("%Y-%m-%d")

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "gh-pages"
        logger.info("Cloning %s (%s)...", repo, branch)
        _clone_gh_pages(repo, branch, clone_dir)

        episodes_dir = clone_dir / "episodes"
        episodes_dir.mkdir(exist_ok=True)
        images_dir = clone_dir / "episode_images"
        images_dir.mkdir(exist_ok=True)

        # 同日再生成時は世代番号を付与（B: ファイル名ユニーク化）
        target_filename = _next_versioned_filename(episodes_dir, today, ".mp3")
        target_mp3 = episodes_dir / target_filename
        shutil.copy2(mp3_source, target_mp3)
        # 旧バージョン削除（重複表示防止）
        removed = _cleanup_old_versions(episodes_dir, today, ".mp3", target_filename)
        if removed > 0:
            logger.info("Removed %d old version(s) of today's mp3", removed)
        logger.info("Copied mp3: %s", target_mp3.name)

        # カバー画像を配置（毎回上書き）
        # 拡張子を維持: cover.jpg または cover.png
        cover_ext = cover_source.suffix.lower()
        cover_dst = clone_dir / f"cover{cover_ext}"
        shutil.copy2(cover_source, cover_dst)
        # 旧cover.pngが存在する場合は削除（拡張子が変わったとき用）
        for old in ["cover.png", "cover.jpg", "cover.jpeg"]:
            if old != cover_dst.name and (clone_dir / old).exists():
                (clone_dir / old).unlink()
        logger.info("Copied cover image: %s", cover_dst.name)

        # エピソード画像を配置（mp3と同じ世代番号を共有）
        if episode_image_source and episode_image_source.exists():
            ep_ext = episode_image_source.suffix.lower()
            # mp3 のステムから世代部分を継承（例: 2026-05-04-r2）
            ep_stem = Path(target_filename).stem
            ep_dst = images_dir / f"{ep_stem}{ep_ext}"
            shutil.copy2(episode_image_source, ep_dst)
            # 同日の古い画像を削除
            for old in images_dir.glob(f"{today}*"):
                if old.name != ep_dst.name:
                    old.unlink()
            logger.info("Copied episode image: %s", ep_dst.name)

        cover_url = f"{pages_url}/cover{cover_ext}"
        feed_xml = _build_feed(
            podcast_meta=podcast_meta,
            pages_url=pages_url,
            episodes_dir=episodes_dir,
            images_dir=images_dir,
            cover_url=cover_url,
            owner_email=owner_email,
        )
        feed_path = clone_dir / "feed.xml"
        feed_path.write_text(feed_xml, encoding="utf-8")
        logger.info("Generated feed.xml with %d episodes",
                    len(list(episodes_dir.glob("*.mp3"))))

        _run(["git", "add", "."], cwd=clone_dir)

        status = _run(["git", "status", "--porcelain"], cwd=clone_dir)
        if not status.strip():
            logger.info("No changes to push")
            return f"{pages_url}/episodes/{target_filename}"

        _run(["git", "commit", "-m", f"Episode {today}"], cwd=clone_dir)
        logger.info("Pushing to origin/%s...", branch)
        _run(["git", "push", "origin", branch], cwd=clone_dir)

    episode_url = f"{pages_url}/episodes/{target_filename}"
    feed_url = f"{pages_url}/feed.xml"
    logger.info("Published: %s", episode_url)
    logger.info("Feed: %s", feed_url)
    return episode_url
