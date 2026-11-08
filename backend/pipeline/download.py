"""Polite downloading into data/raw/, shared by the fetch_* scripts.

Every source a fetch script downloads lives under data/raw/<source>/, which
Git LFS stores, so the rest of the pipeline reads only those files and never
the sites they came from. A fetch script skips every file already saved, so
rerunning it without --refresh touches the network only for files it has
not saved yet.

Each source directory holds manifest.jsonl: one line per saved file, with
its path in the directory, the URL it was fetched from (for a Wayback
capture, the original URL), the capture's timestamp where there is one,
and its SHA-256 and size. Manifest keeps it: loaded from the file, updated
by save(), and rewritten by write(), which also lists any file on disk that
has no record, with no URL.

Requests to one host are spaced apart (HOST_GAP), across processes too, and
transient failures (429, 5xx, connection errors) are retried with backoff.
The Wayback Machine and Arch answer bursts with refusals, so they get long
gaps.

The CDX listings a script picks captures from are saved too (cdx()), so
that rerunning it picks the same captures without asking the Wayback
Machine again.
"""

import fcntl
import hashlib
import json
import tempfile
import time
import urllib.parse
from pathlib import Path

import httpx

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
HEADERS = {"User-Agent": "grantsearch/0.1 (student research search tool)"}
WAYBACK = "https://web.archive.org"
# Seconds between requests to one host.
GAP = 1.1
HOST_GAP = {"web.archive.org": 3.0, "arch.library.northwestern.edu": 20.0}
RETRY = {429, 500, 502, 503, 504, 520, 522, 524}
LOCKS = Path(tempfile.gettempdir()) / "grantsearch-download-locks"

_client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "unknown"


def _wait_turn(host: str) -> None:
    """Sleep until host's gap since the last request (by any process) is up."""
    LOCKS.mkdir(exist_ok=True)
    with open(LOCKS / f"{host}.lock", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            last = float(fh.read().strip() or 0)
        except ValueError:
            last = 0
        wait = last + HOST_GAP.get(host, GAP) - time.time()
        if wait > 0:
            time.sleep(wait)
        fh.seek(0)
        fh.truncate()
        fh.write(str(time.time()))


def get(url: str, tries: int = 7, **kwargs) -> httpx.Response | None:
    """GET url politely. The final response, whatever its status, or None if
    every try failed to connect."""
    delay = 30 if _host(url) == "web.archive.org" else 5
    resp = None
    for attempt in range(tries):
        _wait_turn(_host(url))
        try:
            resp = _client.get(url, **kwargs)
        except httpx.TransportError as e:
            print(f"  retry {attempt + 1} for {url}: {e!r}; sleep {delay}s", flush=True)
        else:
            if resp.status_code not in RETRY:
                return resp
            after = resp.headers.get("retry-after", "")
            if after.isdigit():
                delay = max(delay, min(int(after), 300))
            print(f"  retry {attempt + 1} for {url}: HTTP {resp.status_code}; sleep {delay}s", flush=True)
        if attempt == tries - 1:
            break
        time.sleep(delay)
        delay = min(delay * 2, 240)
    return resp


def wayback(timestamp: str, url: str) -> str:
    """A capture's address in its original form, without the Wayback banner."""
    return f"{WAYBACK}/web/{timestamp}id_/{url}"


def cdx(path: Path, url: str, refresh: bool = False, **params) -> list[dict]:
    """The Wayback CDX listing for url, saved at path (JSON) the first time
    and read from there after. params are passed to the CDX API; a list value
    repeats its key (filter)."""
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    query = [("url", url), ("output", "json")]
    for k, v in params.items():
        query += [(k, x) for x in (v if isinstance(v, list) else [v])]
    resp = get(f"{WAYBACK}/cdx/search/cdx?" + urllib.parse.urlencode(query))
    if resp is None or resp.status_code != 200:
        raise RuntimeError(f"CDX listing for {url} failed: {resp and resp.status_code}")
    rows = resp.json() if resp.text.strip() else []
    out = [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    return out


class Manifest:
    """A source directory's manifest.jsonl, keyed by path in the directory."""

    def __init__(self, source: str, directory: Path | None = None):
        """source's directory under data/raw/, or directory if given (a
        checkout of another repository, for files kept out of this one)."""
        self.dir = directory or RAW / source
        self.path = self.dir / "manifest.jsonl"
        self.records: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.open():
                r = json.loads(line)
                self.records[r["path"]] = r

    def save(self, rel: str, url: str, source_url: str | None = None, timestamp: str | None = None,
             refresh: bool = False, ok=(200,), check=None, headers=None, **extra) -> Path | None:
        """Fetch url into <source>/<rel> unless it is saved already; the saved
        path, or None if the response was refused. check, given the body,
        says whether it is the file wanted (an error page may answer 200).
        headers are added to the request (a Range, say)."""
        dest = self.dir / rel
        if dest.exists() and dest.stat().st_size and not refresh:
            # A file saved before it had a record (copied in, say) gets one.
            if not (self.records.get(rel) or {}).get("source_url"):
                self.records[rel] = {"path": rel, "source_url": source_url or url, "capture_timestamp": timestamp, **extra}
            return dest
        resp = get(url, headers=headers)
        if resp is None or resp.status_code not in ok or (check and not check(resp.content)):
            print(f"FAIL {url}: {resp.status_code if resp is not None else 'no response'}", flush=True)
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        self.records[rel] = {"path": rel, "source_url": source_url or url, "capture_timestamp": timestamp, **extra}
        print(f"ok {len(resp.content):>9} {rel}", flush=True)
        return dest

    def save_wayback(self, rel: str, timestamp: str, url: str, **kwargs) -> Path | None:
        return self.save(rel, wayback(timestamp, url), source_url=url, timestamp=timestamp, **kwargs)

    def listing(self, name: str, url: str, params: dict, refresh: bool = False) -> list[dict]:
        """The CDX listing captures are picked from (see cdx()), saved as
        cdx/<name>.json and recorded with the query that answered it."""
        rel = f"cdx/{name}.json"
        rows = cdx(self.dir / rel, url, refresh, **params)
        query = [("url", url), ("output", "json")]
        query += [(k, x) for k, v in params.items() for x in (v if isinstance(v, list) else [v])]
        self.records.setdefault(rel, {"path": rel, "source_url": f"{WAYBACK}/cdx/search/cdx?{urllib.parse.urlencode(query)}",
                                      "capture_timestamp": None})
        return rows

    def write(self) -> None:
        """Rewrite manifest.jsonl from the files on disk. Records another
        script wrote to the same manifest since this one loaded it are kept."""
        if self.path.exists():
            for line in self.path.open():
                r = json.loads(line)
                self.records.setdefault(r["path"], r)
        out = []
        for f in sorted(p for p in self.dir.rglob("*") if p.is_file()):
            rel = str(f.relative_to(self.dir))
            # A checkout of another repository keeps its own files beside the downloads.
            if rel in ("manifest.jsonl", ".gitattributes", ".gitignore", "README.md") or rel.startswith(".git/"):
                continue
            data = f.read_bytes()
            r = self.records.get(rel, {"path": rel, "source_url": None, "capture_timestamp": None})
            out.append({**r, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        self.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
        print(f"{self.dir.name}: {len(out)} files, {sum(r['bytes'] for r in out):,} bytes -> {self.path}")
