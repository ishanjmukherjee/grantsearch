"""The query log: what visitors search, what they were shown and what they did with it.

Events go to one append-only Postgres table, events, when DATABASE_URL is set;
without it (development, scripts) nothing is logged. Each row is

- at: when the server recorded it
- visit: the random id a browser tab sends with its requests (see visit in
  frontend/src/App.tsx), kept in the tab's sessionStorage, so it links one
  tab's searches and clicks and ends when the tab closes. None for a request
  the frontend did not make, such as a script's or a crawler's.
- kind: "search", "project" (a project page was loaded), or what the visitor
  did with a result: "click", "expand" (opened a clamped abstract) or "share"
- internal: the visitor marked their browser as the site's own (opening
  /?internal=1 once sets it, /?internal=0 clears it), so that building and
  testing the site can be left out of what visitors do
- data: the rest, as JSON:
  - every kind: device ("mobile", "desktop" or "bot", read from the
    User-Agent, which is not kept) and sha, the commit the server runs
  - search: q as sent, source, from, to, n, offset, total, results (the ids
    of the projects returned, in order), ms (how long the search took), and
    from the browser seq (the search's number within the visit), shown (the
    seq of the results on screen when it was sent, None before any) and
    cause: "load" (the page opened on it, as from a link), "type", "filter",
    "page" or "back".
  - project: number (the share number asked for), project (its id, None if
    there is no such project) and similar (the ids listed under it)
  - click, expand, share: project, and where the result was, as on:
    "search" (among a search's results, with that search's seq and the
    result's rank in its whole ranking, from 1), "project" (the project a
    page is for) or "similar" (listed under it, with its rank there). A
    click adds link, "page" for the title, which opens the project's page,
    or else the source a link leaves the site for, and record, the record or
    listing the link is for. An expand adds record, the abstract's.

Results update as a visitor types, so most searches are of a query half
typed. Every one is logged, since each is a list of results someone may have
seen; which were the query a visitor settled on is for the analysis to say
(the last before a pause, a click or the visit's end). A request the next
keystroke aborts still reaches the server, so shown says which results were
really on screen: a search is seen if a later event of its visit names its
seq as shown, or as its own seq.

No IP address, cookie or User-Agent is stored. Queries often name people, so
the log is private: it stays in the database, never in this repository.
Nothing is deleted from it.

Logging must never slow or break a search: put() only adds to a bounded queue
that one thread writes from. While the database is unreachable the queue
holds up to MAX_QUEUE events, and those that arrive when it is full are
dropped.

Usage: python -m querylog export [--days N]
prints the log as JSON lines, oldest first. The database is reachable only
inside the Railway project, so run it in the deployed service:
railway ssh --service web python -m querylog export --days 7
"""

import argparse
import contextlib
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import UTC, datetime

KINDS = ("click", "expand", "share")  # what a browser may report; the server writes the others
PLACES = ("search", "project", "similar")
MAX_QUEUE = 10_000
BATCH = 500
# Browser events accepted a minute, over all visitors: the endpoint is open,
# so this bounds what a flood can write.
MAX_REPORTS = 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at timestamptz NOT NULL,
    visit text,
    kind text NOT NULL,
    internal boolean NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS events_at ON events (at);
CREATE INDEX IF NOT EXISTS events_visit ON events (visit, at);
"""

VISIT = re.compile(r"[A-Za-z0-9_-]{8,40}")
ID = re.compile(r"[a-z_]+-\d{4}-\d+")
LINK = re.compile(r"[a-z_]{1,20}")
BOT = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|curl|wget|python|httpx|headless", re.IGNORECASE)
MOBILE = re.compile(r"Mobi|Android|iPhone|iPad")


def device(user_agent: str | None) -> str:
    if not user_agent or BOT.search(user_agent):
        return "bot"
    return "mobile" if MOBILE.search(user_agent) else "desktop"


def visit(value: str | None) -> str | None:
    """A visit id as the frontend makes them, or None for anything else."""
    return value if value and VISIT.fullmatch(value) else None


def number(value) -> int | None:
    """A count a browser sent (a seq or a rank), or None for anything else."""
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**9 else None


def report(body: bytes, known: set[str]) -> tuple[str | None, str, bool, dict] | None:
    """A browser's report of what a visitor did with a result, as put() takes
    it, or None when it is not one: the endpoint is open to anyone, so only
    the fields above are kept, each checked, and the project and record must
    be among known, the ids of the site's records and listings."""
    try:
        sent = json.loads(body)
    except ValueError:
        return None
    if not isinstance(sent, dict) or sent.get("kind") not in KINDS:
        return None
    if not isinstance(sent.get("project"), str) or sent["project"] not in known or sent.get("on") not in PLACES:
        return None
    data = {"project": sent["project"], "on": sent["on"], "seq": number(sent.get("seq")), "rank": number(sent.get("rank"))}
    if sent["kind"] != "share":
        record = sent.get("record")
        data["record"] = record if isinstance(record, str) and record in known else None
    if sent["kind"] == "click":
        link = sent.get("link")
        if not isinstance(link, str) or not LINK.fullmatch(link):
            return None
        data["link"] = link
    return visit(sent.get("visit")), sent["kind"], sent.get("internal") is True, data


class QueryLog:
    def __init__(self) -> None:
        self.url = os.environ.get("DATABASE_URL")
        self.sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        self.queue: queue.Queue = queue.Queue(MAX_QUEUE)
        self.reports = (0, 0)  # the minute being counted, and the browser events accepted in it
        self.thread = None
        if self.url:
            self.thread = threading.Thread(target=self.write, name="querylog", daemon=True)
            self.thread.start()

    def put(self, visit: str | None, kind: str, internal: bool, user_agent: str | None, data: dict) -> None:
        """Queue an event; dropped when logging is off or the queue is full."""
        if not self.thread:
            return
        row = (datetime.now(UTC), visit, kind, internal, json.dumps(data | {"device": device(user_agent), "sha": self.sha}))
        try:
            self.queue.put_nowait(row)
        except queue.Full:
            pass

    def allow_report(self) -> bool:
        """Whether one more browser event fits in this minute's MAX_REPORTS."""
        minute = int(time.monotonic() // 60)
        counted, n = self.reports
        if counted != minute:
            n = 0
        self.reports = (minute, n + 1)
        return n < MAX_REPORTS

    def close(self) -> None:
        """Write what is queued and stop, waiting a few seconds at most."""
        if self.thread:
            self.queue.put(None)
            self.thread.join(timeout=5)

    def write(self) -> None:
        """The writer thread: makes the table, then inserts events in
        batches. While the database cannot be reached it keeps its batch and
        tries again, the queue holding what arrives meanwhile; an event the
        database refuses is dropped."""
        import psycopg

        insert = "INSERT INTO events (at, visit, kind, internal, data) VALUES (%s, %s, %s, %s, %s)"
        conn, batch, failures = None, [], 0
        while True:
            try:
                if conn is None:
                    conn = psycopg.connect(self.url, autocommit=True, connect_timeout=10)
                    conn.execute(SCHEMA)
                if not batch:
                    batch = self.take()
                rows = [row for row in batch if row is not None]
                try:
                    with conn.transaction(), conn.cursor() as cur:
                        cur.executemany(insert, rows)
                except psycopg.OperationalError:
                    raise
                except psycopg.DatabaseError:
                    # One of them is refused; write the others.
                    for row in rows:
                        try:
                            conn.execute(insert, row)
                        except psycopg.OperationalError:
                            raise
                        except psycopg.DatabaseError as e:
                            print(f"querylog: dropped an event ({type(e).__name__})", file=sys.stderr, flush=True)
                if None in batch:
                    return
                batch, failures = [], 0
            except (psycopg.Error, OSError) as e:
                # Never the events themselves: they hold what people searched.
                print(f"querylog: {type(e).__name__} with {len(batch)} events to write", file=sys.stderr, flush=True)
                if conn is not None:
                    with contextlib.suppress(psycopg.Error, OSError):
                        conn.close()
                    conn = None
                failures += 1
                if None in batch:
                    return
                time.sleep(min(60, 5 * failures))

    def take(self) -> list:
        """The next events to write, waiting up to a minute for the first;
        None among them asks the writer to stop."""
        try:
            batch = [self.queue.get(timeout=60)]
        except queue.Empty:
            return []
        try:
            while len(batch) < BATCH:
                batch.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return batch


def export(days: int | None) -> None:
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL to the log's database.")
    where = "WHERE at >= now() - make_interval(days => %s)" if days is not None else ""
    with psycopg.connect(url) as conn, conn.cursor(name="export") as cur:
        cur.execute(f"SELECT at, visit, kind, internal, data FROM events {where} ORDER BY at, id", (days,) if days is not None else None)
        for at, visit_id, kind, internal, data in cur:
            print(json.dumps({"at": at.isoformat(), "visit": visit_id, "kind": kind, "internal": internal} | data, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    exporting = commands.add_parser("export", help="print the log as JSON lines, oldest first")
    exporting.add_argument("--days", type=int, help="only the last N days")
    args = parser.parse_args()
    export(args.days)


if __name__ == "__main__":
    main()
