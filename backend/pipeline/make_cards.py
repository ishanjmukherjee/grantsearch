"""Generate search cards for grants and Expo projects.

Runs one headless `claude -p` call per item, in parallel, with no tools.
Workers only print JSON; this script is the single writer of the output and
adds the item id itself, so the model never handles ids. The prompt's
placeholders are filled per item. Items already in the output are skipped, so
an interrupted run resumes by rerunning. Calls that fail twice go to a
matching *_errors.jsonl. Modes:

- title (default): a concept card or refusal from each grant's title alone,
  prompts/concept_card.md -> data/cards.jsonl.
- abstract: grants with linked Expo abstracts, prompts/abstract_card.md ->
  data/cards_abstract.jsonl.
- expo: Expo posters not linked to a grant, prompts/expo_card.md ->
  data/cards_expo.jsonl, keyed by the poster's first listing. A poster listed
  once per presenter gets one card from all its listings.
- gloss: a short topic-level gloss for every project with abstracts (linked
  grants and unlinked Expo posters), prompts/abstract_gloss.md ->
  data/glosses.jsonl.

Usage: uv run python -m pipeline.make_cards [--mode title|abstract|expo|gloss] [--fresh] [--limit N] [--ids ID ...] [--jobs 8] [--model M]
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from pipeline.link_expo import linked_abstracts, unlinked_groups
from pipeline.scrape_surg import DATA_DIR

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
# (prompt, output) per mode.
PATHS = {
    "title": (PROMPT_DIR / "concept_card.md", DATA_DIR / "cards.jsonl"),
    "abstract": (PROMPT_DIR / "abstract_card.md", DATA_DIR / "cards_abstract.jsonl"),
    "expo": (PROMPT_DIR / "expo_card.md", DATA_DIR / "cards_expo.jsonl"),
    "gloss": (PROMPT_DIR / "abstract_gloss.md", DATA_DIR / "glosses.jsonl"),
}
MODEL = "claude-opus-5-5"
EFFORT = "medium"
TIMEOUT = 300
SYSTEM = "Follow the user's instructions exactly. Reply with one JSON object and nothing else."

CARD_KEYS = {"gloss": str, "fields": list, "concepts": list, "acronyms": dict, "queries": list}
ABSTRACT_KEYS = {k: CARD_KEYS[k] for k in ("fields", "concepts", "acronyms", "queries")}


def check(obj: dict, mode: str) -> dict:
    """Return the card, refusal or gloss with only its own keys, or raise."""
    if mode == "gloss":
        if not isinstance(obj.get("gloss"), str) or not obj["gloss"]:
            raise ValueError("missing gloss")
        return {"gloss": obj["gloss"]}
    if mode != "title":
        for key, typ in ABSTRACT_KEYS.items():
            if not isinstance(obj.get(key), typ):
                raise ValueError(f"card field {key!r} missing or not {typ.__name__}")
        if len(obj["queries"]) != 10:
            raise ValueError(f"{len(obj['queries'])} queries")
        return {k: obj[k] for k in ABSTRACT_KEYS}
    if obj.get("status") == "refuse":
        if not isinstance(obj.get("reason"), str) or not obj["reason"]:
            raise ValueError("refusal without reason")
        return {"status": "refuse", "reason": obj["reason"]}
    if obj.get("status") == "card":
        for key, typ in CARD_KEYS.items():
            if not isinstance(obj.get(key), typ):
                raise ValueError(f"card field {key!r} missing or not {typ.__name__}")
        if not 1 <= len(obj["queries"]) <= 10:
            raise ValueError(f"{len(obj['queries'])} queries")
        return {"status": "card", **{k: obj[k] for k in CARD_KEYS}}
    raise ValueError(f"bad status {obj.get('status')!r}")


def parse(stdout: bytes) -> dict:
    """Pull the model's JSON object out of `claude -p --output-format json`."""
    envelope = json.loads(stdout)
    if envelope.get("is_error"):
        raise ValueError(f"claude error: {envelope.get('result')}")
    text = envelope["result"].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


async def call(prompt: str, cwd: str, mode: str, model: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p",
        "--model", model,
        "--effort", EFFORT,
        "--system-prompt", SYSTEM,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--output-format", "json",
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {stderr.decode()[-500:]}")
    return check(parse(stdout), mode)


def names(people: list[dict]) -> str:
    return "; ".join(f"{p['first']} {p['last']}" for p in people)


def poster(listings: list[dict]) -> dict:
    """One card item for an Expo poster's listings: the first's title, everyone's presenters and advisors."""
    first = listings[0]
    advisors = list(dict.fromkeys(e["advisor"] for e in listings if e["advisor"]))
    return {
        "id": first["id"],
        "title": first["title"],
        "year": first["year"],
        "presenters": [p for e in listings for p in e["presenters"]],
        "advisor": "; ".join(advisors) or None,
        "abstract": "\n\n".join(dict.fromkeys(e["abstract"] for e in listings)),
    }


def expo_entries(entries: list[dict]) -> str:
    # A poster's listings often repeat one abstract; show it once.
    distinct: dict[str, dict] = {}
    for e in entries:
        distinct.setdefault(e["abstract"], e)
    return "\n\n".join(
        f"Expo abstract ({e['year']}): \"{e['title']}\"\nAdvisor: {e['advisor'] or 'not listed'}\n{e['abstract']}"
        for e in distinct.values()
    )


def slots(mode: str, item: dict, linked: dict[str, list[dict]]) -> dict[str, str]:
    """The prompt's placeholders and their values for one item."""
    if mode == "gloss":
        return {"{title}": item["title"], "{abstracts}": expo_entries(item["entries"])}
    s = {"{title}": item["title"], "{year}": str(item["year"])}
    if mode == "expo":
        return s | {
            "{presenters}": names(item["presenters"]),
            "{advisor}": item["advisor"] or "not listed",
            "{abstract}": item["abstract"],
        }
    s["{awardees}"] = names(item["awardees"])
    if mode == "abstract":
        s["{abstracts}"] = expo_entries(linked[item["id"]])
    return s


async def run(items: list[dict], jobs: int, mode: str, linked: dict[str, list[dict]], model: str) -> None:
    prompt_path, out = PATHS[mode]
    errors = out.with_name(out.stem + "_errors.jsonl")
    template = prompt_path.read_text()
    sem = asyncio.Semaphore(jobs)
    done = 0

    async def one(item: dict, cwd: str) -> None:
        nonlocal done
        prompt = template
        for slot, value in slots(mode, item, linked).items():
            if slot not in template:
                raise SystemExit(f"{prompt_path} is missing the {slot} placeholder")
            prompt = prompt.replace(slot, value)
        async with sem:
            error = None
            for _ in range(2):
                try:
                    result = await call(prompt, cwd, mode, model)
                    break
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
            else:
                with errors.open("a") as f:
                    f.write(json.dumps({"id": item["id"], "title": item["title"], "error": error}) + "\n")
                print(f"FAILED {item['id']}: {error}")
                return
        with out.open("a") as f:
            f.write(json.dumps({"id": item["id"], "title": item["title"], **result}) + "\n")
        done += 1
        print(f"[{done}/{len(items)}] {item['id']} {result.get('status', 'card')}")

    # An empty working directory keeps project CLAUDE.md files out of the workers.
    with tempfile.TemporaryDirectory() as cwd:
        await asyncio.gather(*(one(item, cwd) for item in items))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=PATHS, default="title", help="which cards to generate")
    parser.add_argument("--fresh", action="store_true", help="delete existing cards and errors first")
    parser.add_argument("--limit", type=int, help="only process the first N pending items")
    parser.add_argument("--ids", nargs="+", help="only process these ids")
    parser.add_argument("--jobs", type=int, default=8, help="parallel claude calls")
    parser.add_argument("--model", default=MODEL, help="claude model")
    args = parser.parse_args()

    out = PATHS[args.mode][1]
    if args.fresh:
        out.unlink(missing_ok=True)
        out.with_name(out.stem + "_errors.jsonl").unlink(missing_ok=True)
    have = {json.loads(line)["id"] for line in out.open()} if out.exists() else set()

    linked = linked_abstracts()
    if args.mode == "expo":
        items = [poster(g) for g in unlinked_groups(linked)]
    elif args.mode == "gloss":
        grants = [g for g in json.loads((DATA_DIR / "grants.json").read_text()) if g["id"] in linked]
        items = [{"id": g["id"], "title": g["title"], "entries": linked[g["id"]]} for g in grants]
        items += [{"id": g[0]["id"], "title": g[0]["title"], "entries": g} for g in unlinked_groups(linked)]
    else:
        items = json.loads((DATA_DIR / "grants.json").read_text())
        if args.mode == "abstract":
            items = [g for g in items if g["id"] in linked]
    pending = [x for x in items if x["id"] not in have and (not args.ids or x["id"] in args.ids)]
    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(have)} done, {len(pending)} to run")
    asyncio.run(run(pending, args.jobs, args.mode, linked, args.model))


if __name__ == "__main__":
    main()
