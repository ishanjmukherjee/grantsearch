"""Download the YouTube voiceovers of the 2022 Expo's ForagerOne posters.

Each nuexpo22 poster (pipeline.scrape_forager, data/raw/forager_nuexpo22/)
links one recorded voiceover on YouTube in originalVoiceoverLink: 123
posters, 123 videos. The students posted them unlisted, so like Expo 2020's
(the private expo2020-videos repository) they are kept out of this public
repository, in a checkout of the private expo2022-videos repository
(https://github.com/ishanjmukherjee/expo2022-videos), read from
EXPO2022_VIDEOS, by default expo2022-videos-wt/expo2022-videos beside this
repository's grantsearch-wt. Each is saved under videos/<presentation id>/
there as the video at up to 720p with its audio, its captions (uploaded or
automatic, English) as .vtt, and yt-dlp's info JSON, the same way as
pipeline.fetch_nurj_extra saves NURJ's videos, with videos/unavailable.json
and manifest.jsonl beside them.

YouTube answers a burst of downloads from one address with "Sign in to
confirm you're not a bot" for every video, for hours, and its video servers
sometimes answer 403 partway through a download. So this waits a few
minutes between videos, and on either answer it waits longer each time
(half an hour, doubling to four hours) and tries the same video again; it
never records a refusal of that kind as the video being gone. Videos that are
private or removed are listed in unavailable.json and not tried again
without --refresh.

Node runs YouTube's player JavaScript (yt-dlp misses formats without a JS
runtime); it is looked for on PATH and in ~/.local/node/bin.

Usage: uv run python -m pipeline.fetch_forager_videos [--refresh]
"""

import argparse
import json
import os
import random
import re
import time

from pathlib import Path

import yt_dlp

from pipeline.download import RAW, Manifest
from pipeline.fetch_nurj_extra import FORMAT, node

SOURCE = "forager_nuexpo22_videos"
EVENT_DIR = RAW / "forager_nuexpo22"
CHECKOUT = Path(__file__).resolve().parents[4] / "expo2022-videos-wt" / "expo2022-videos"
YOUTUBE_ID = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})")
# Seconds between videos, and the first and longest waits after a bot check.
GAP = (180, 360)
BOT_WAIT, BOT_WAIT_MAX = 1800, 4 * 3600
# YouTube's refusals that pass with time, unlike a private or removed video:
# the bot check, and a 403 or 429 from its video servers mid-download.
BOT_CHECK = re.compile(r"confirm you.re not a bot|HTTP Error (403|429)", re.I)


def voiceovers() -> dict[str, str]:
    """Presentation id -> YouTube id of its voiceover."""
    out = {}
    for f in sorted(EVENT_DIR.glob("*/presentation.json")):
        link = json.loads(f.read_text()).get("originalVoiceoverLink") or ""
        if m := YOUTUBE_ID.search(link):
            out[f.parent.name] = m.group(1)
    return out


def saved(out: Path, pid: str) -> bool:
    return any(f.suffix not in (".json", ".vtt", ".part", ".ytdl") for f in (out / pid).glob("*"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch saved videos and retry the unavailable")
    args = parser.parse_args()
    checkout = Path(os.environ.get("EXPO2022_VIDEOS", CHECKOUT))
    if not (checkout / ".git").exists():
        raise SystemExit(f"no expo2022-videos checkout at {checkout} (set EXPO2022_VIDEOS)")
    out = checkout / "videos"
    manifest = Manifest(SOURCE, checkout)
    gone_path = out / "unavailable.json"
    gone = {} if args.refresh or not gone_path.exists() else json.loads(gone_path.read_text())
    videos = voiceovers()
    todo = [(pid, vid) for pid, vid in videos.items() if pid not in gone and (args.refresh or not saved(out, pid))]
    print(f"{len(videos)} voiceovers, {len(todo)} to fetch", flush=True)
    options = {
        "format": FORMAT,
        "merge_output_format": "mp4/webm",
        "writeinfojson": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en.*", "-live_chat"],
        "subtitlesformat": "vtt",
        "overwrites": args.refresh,
        "quiet": True,
        "no_warnings": True,
    }
    if js := node():
        options["js_runtimes"] = {"node": {"path": js}}
    wait = BOT_WAIT
    for n, (pid, vid) in enumerate(todo):
        url = f"https://www.youtube.com/watch?v={vid}"
        opts = {**options, "outtmpl": {"default": f"{pid}/{vid}.%(ext)s", "infojson": f"{pid}/{vid}", "subtitle": f"{pid}/{vid}"},
                "paths": {"home": str(out)}}
        while True:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                message = re.sub(r"\s+", " ", str(e)).removeprefix("ERROR: ")
                if BOT_CHECK.search(message):
                    print(f"bot check on {vid}; waiting {wait // 60} min", flush=True)
                    time.sleep(wait)
                    wait = min(wait * 2, BOT_WAIT_MAX)
                    continue
                gone[pid] = {"video": vid, "reason": message.split(". ")[0]}
                print(f"unavailable {pid} {vid}: {gone[pid]['reason']}", flush=True)
            else:
                wait = BOT_WAIT
                for f in sorted((out / pid).glob("*")):
                    rel = str(f.relative_to(checkout))
                    manifest.records[rel] = {"path": rel, "source_url": url, "capture_timestamp": None}
                print(f"ok {n + 1}/{len(todo)} {pid} {vid}", flush=True)
            break
        gone_path.parent.mkdir(parents=True, exist_ok=True)
        gone_path.write_text(json.dumps(dict(sorted(gone.items())), indent=1) + "\n")
        if (n + 1) % 10 == 0:
            manifest.write()
        if n + 1 < len(todo):
            time.sleep(random.uniform(*GAP))
    gone_path.parent.mkdir(parents=True, exist_ok=True)
    gone_path.write_text(json.dumps(dict(sorted(gone.items())), indent=1) + "\n")
    manifest.write()
    print(f"{len(videos)} voiceovers, {len(videos) - len(gone)} saved, {len(gone)} unavailable")


if __name__ == "__main__":
    main()
