"""Download the NURJ media that scrape_nurj keeps only as URLs, into data/raw/nurj_extra/.

Two kinds, both linked or embedded by the posts and pages in data/nurj.json:

- youtube/<video id>/: the YouTube videos the posts embed or link (40 ids,
  mostly NURJ's recorded presentations). Each is saved at up to 720p with its
  audio, as an mp4 where YouTube serves one (else whatever container the
  formats need), with YouTube's English captions, uploaded or automatic, as
  .vtt, and yt-dlp's metadata (.info.json). Videos that are private or gone
  are listed in youtube/unavailable.json with the error YouTube gave, and
  are not asked for again without --refresh.
- media/: the files the site serves from thenurj.com/wp-content/uploads/:
  every WordPress media item (data/nurj.json "media") and every other
  uploads file the posts, pages and saved renderings link, at its uploads
  path (media/uploads/2021/03/x.mp3). WordPress's resized copies of an image
  (name-300x200.jpg) are left out where the original is among them, as are
  the stylesheets Elementor writes to uploads/. The 22 PDFs scrape_nurj saves
  under data/raw/nurj/files/ are not downloaded again. Files the site no
  longer serves are listed in media/missing.json.

Node runs YouTube's player JavaScript (yt-dlp misses formats without a JS
runtime); it is looked for on PATH and in ~/.local/node/bin.

manifest.jsonl is shared with pipeline.fetch_nurj_documents, which saves
other files here; each script keeps the other's records.

Usage: uv run python -m pipeline.fetch_nurj_extra [--refresh]
"""

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yt_dlp

from pipeline.download import RAW, Manifest

SOURCE = "nurj_extra"
NURJ = RAW.parents[0] / "nurj.json"
NURJ_RAW = RAW / "nurj"
OUT = RAW / SOURCE
YOUTUBE_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})")
UPLOADS = re.compile(r"https?://(?:www\.)?thenurj\.com/wp-content/uploads/[^\s\"'<>\\)&?#]+")
RESIZED = re.compile(r"-\d+x\d+(?=\.\w+$)")
# Prefer formats that merge into an mp4; fall back to any up to 720p.
FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]/b"


def node() -> str | None:
    return shutil.which("node") or next((str(p) for p in [Path.home() / ".local/node/bin/node"] if p.exists()), None)


def video_ids() -> list[str]:
    return sorted(set(YOUTUBE_ID.findall(NURJ.read_text())))


def upload_urls() -> list[str]:
    """The uploads files to save: media items, and the other files linked,
    without resized copies of an original among them or Elementor's CSS."""
    texts = [NURJ.read_text()] + [p.read_text(errors="replace") for p in NURJ_RAW.glob("*.json")]
    texts += [p.read_text(errors="replace") for p in (NURJ_RAW / "rendered").rglob("*") if p.is_file()]
    texts.append((NURJ_RAW / "home.html").read_text(errors="replace"))
    urls = {m["source_url"] for m in json.loads(NURJ.read_text())["media"]}
    urls |= {u for t in texts for u in UPLOADS.findall(t)}
    urls = {re.sub(r"^https?://(?:www\.)?", "https://", u) for u in urls}
    urls = {u for u in urls if not u.lower().endswith(".css")}
    return sorted(u for u in urls if not (RESIZED.search(u) and RESIZED.sub("", u) in urls))


def uploads_path(url: str) -> str:
    return unquote(urlsplit(url).path).split("/wp-content/uploads/", 1)[1]


def fetch_media(manifest: Manifest, refresh: bool) -> None:
    missing_path = OUT / "media" / "missing.json"
    missing = {} if refresh or not missing_path.exists() else json.loads(missing_path.read_text())
    urls = upload_urls()
    saved = skipped = 0
    for url in urls:
        rel = uploads_path(url)
        if (NURJ_RAW / "files" / rel).exists():
            skipped += 1
            continue
        if url in missing:
            continue
        if manifest.save(f"media/uploads/{rel}", url, refresh=refresh, ok=(200,)) is None:
            missing[url] = "not served"
        else:
            saved += 1
    missing_path.parent.mkdir(parents=True, exist_ok=True)
    missing_path.write_text(json.dumps(dict(sorted(missing.items())), indent=1) + "\n")
    print(f"media: {len(urls)} files linked, {saved} saved here, {skipped} in data/raw/nurj/files, {len(missing)} not served")


def fetch_videos(manifest: Manifest, refresh: bool) -> None:
    gone_path = OUT / "youtube" / "unavailable.json"
    gone = {} if refresh or not gone_path.exists() else json.loads(gone_path.read_text())
    ids = video_ids()
    todo = [i for i in ids if i not in gone and (refresh or not any(
        f.suffix not in (".json", ".vtt", ".part", ".ytdl") for f in (OUT / "youtube" / i).glob("*")))]
    if todo:
        options = {
            "format": FORMAT,
            "merge_output_format": "mp4/webm",
            "writeinfojson": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*", "-live_chat"],
            "subtitlesformat": "vtt",
            "outtmpl": {"default": "%(id)s/%(id)s.%(ext)s", "infojson": "%(id)s/%(id)s", "subtitle": "%(id)s/%(id)s"},
            "paths": {"home": str(OUT / "youtube")},
            "overwrites": refresh,
            "quiet": True,
            "no_warnings": True,
        }
        if js := node():
            options["js_runtimes"] = {"node": {"path": js}}
        with yt_dlp.YoutubeDL(options) as ydl:
            for i in todo:
                url = f"https://www.youtube.com/watch?v={i}"
                try:
                    ydl.download([url])
                except yt_dlp.utils.DownloadError as e:
                    gone[i] = re.sub(r"\s+", " ", str(e)).split(". ")[0].removeprefix("ERROR: ")
                    print(f"unavailable {i}: {gone[i]}", flush=True)
                    continue
                for f in sorted((OUT / "youtube" / i).glob("*")):
                    manifest.records[str(f.relative_to(OUT))] = {"path": str(f.relative_to(OUT)), "source_url": url, "capture_timestamp": None}
                print(f"ok {i}", flush=True)
    gone_path.parent.mkdir(parents=True, exist_ok=True)
    gone_path.write_text(json.dumps(dict(sorted(gone.items())), indent=1) + "\n")
    print(f"youtube: {len(ids)} videos linked, {len(ids) - len(gone)} saved, {len(gone)} unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch saved files and retry the unavailable")
    args = parser.parse_args()
    manifest = Manifest(SOURCE)
    fetch_videos(manifest, args.refresh)
    fetch_media(manifest, args.refresh)
    # pipeline.fetch_nurj_documents may have written records since this run loaded them.
    for rel, record in Manifest(SOURCE).records.items():
        manifest.records.setdefault(rel, record)
    manifest.write()


if __name__ == "__main__":
    main()
