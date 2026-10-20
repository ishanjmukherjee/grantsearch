"""Parse Undergraduate Research & Arts Expo abstracts, 2021-2026.

Two layouts exist:

- Programs (2021-2023): presenter in bold, "Faculty Advisor:" in italics, title
  in bold, abstract in regular weight, small page footers and (2021) a
  running page header. Parsed line by line from font weights.
- Abstract guides (2024-2026): one font throughout. Each entry is a header
  block (presenter and advisor), a title block, abstract blocks, and a closing
  block starting with "Presentation Format:". Parsed from block boundaries.

Advisor affiliations go in parentheses after the advisor's name, so that
"Joseph Contessa, Yale University" or "Monika Nanda [UNC Chapel Hill]" reads
as one advisor, "Joseph Contessa (Yale University)".

Writes data/expo_abstracts.json.

Usage: uv run python -m pipeline.parse_expo [--refresh]
"""

import argparse
import json
import re
from pathlib import Path

import httpx
import pymupdf

from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR, clean

BASE = "https://undergradresearch.northwestern.edu/files"
SOURCES = {
    2021: f"{BASE}/2024/03/The-2021-Virtual-Undergraduate-Research-and-Arts-Exposition-7e95f42a523aba52.pdf",
    2022: f"{BASE}/2024/03/2022-Undergraduate-Research-Arts-Exposition-Digital-Program-a15a7699ca7c2d29.pdf",
    2023: f"{BASE}/2024/03/2023-Undergraduate-Research-and-Arts-Expo-Program-439f378a3b0164f8.pdf",
    2024: f"{BASE}/2024/05/2024-Exposition-Abstract-Guide.pdf",
    2025: f"{BASE}/2025/05/2025_Expo_Abstract_Guide_05.19.25.pdf",
    2026: f"{BASE}/2026/05/2026-Undergraduate-Research-Expo-Abstract-Guide.pdf",
}
PROGRAM_YEARS = {2021, 2022, 2023}
LAST_FIRST_YEARS = {2025, 2026}

# The guides' font maps the fi and fl ligatures to private-use code points.
LIGATURES = str.maketrans({"\uf001": "fi", "\uf002": "fl"})
PARTICLES = {"van", "von", "den", "der", "de", "da", "del", "della", "di", "du", "dos", "la", "le"}
ADVISOR = re.compile(r"Faculty Advisors?:\s*(.*)", re.S)
GUIDE_END = "Presentation Format:"
# An advisor list item naming an institution rather than a person.
INSTITUTION = re.compile(r"\b(?:University|College|Laboratory|Hospital|Institute|School|Center)\b")
BOLD = 16
MIN_BODY_SIZE = 10  # lines of only smaller text are page footers
# 2021 sets its running page header at body size, so match it by text.
RUNNING_HEADER = re.compile(r"\s*Undergraduate Research & Arts Exposition \d+\s*")


def fetch(year: int, refresh: bool) -> Path:
    path = RAW_DIR / "expo" / f"{year}.pdf"
    if path.exists() and not refresh:
        return path
    resp = httpx.get(SOURCES[year], headers=HEADERS, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def text(s: str) -> str:
    s = s.translate(LIGATURES).replace("&amp;", "&")
    # Rejoin words hyphenated across line breaks.
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)
    s = clean(s)
    # Drop stray spaces inside brackets ("[PSI+ ]") and before punctuation
    # ("results ,"), but not before a decimal point ("p < .001").
    s = re.sub(r"([(\[]) +| +([)\]])", r"\1\2", s)
    return re.sub(r"(?<=[\w)\]\"']) +([,;:.])(?=\s|$)", r"\1", s)


def affiliations(advisor: str) -> str:
    """Put an advisor's affiliation in parentheses after their name."""
    advisor = re.sub(r"\s*\[([^\]]*)\]", r" (\1)", advisor)
    items = re.split(r"\s*,\s*", advisor)
    out = [items[0]]
    for item in items[1:]:
        if INSTITUTION.search(item) and not out[-1].endswith(")"):
            out[-1] += f" ({item})"
        else:
            out.append(item)
    return ", ".join(out)


def split_people(s: str, last_first: bool) -> list[dict]:
    """Split a presenter string into first/last names.

    Older years list "First Last and First Last"; 2025 on list "Last, First"
    with several presenters separated by semicolons or line breaks.
    """
    people = []
    if last_first:
        for part in re.split(r"\s*(?:;|\n|&| and )\s*", s):
            if "," in part:
                last, first = (p.strip() for p in part.split(",", 1))
                if first and last:
                    people.append({"first": text(first), "last": text(last)})
    else:
        for part in re.split(r"\s*(?:,\s*and\s+|,|;|\n|&| and )\s*", s):
            words = part.split()
            if len(words) >= 2:
                cut = len(words) - 1
                while cut > 1 and words[cut - 1].lower() in PARTICLES:
                    cut -= 1
                people.append({"first": text(" ".join(words[:cut])), "last": text(" ".join(words[cut:]))})
    return people


def entry(people: list[dict], advisor: str | None, title: str, abstract: str) -> dict | None:
    if not people or not title or not abstract:
        return None
    return {"presenters": people, "advisor": advisor or None, "title": title, "abstract": abstract}


def join_spans(spans: list[dict]) -> str:
    """Join a line's font runs, restoring spaces the PDF encodes as gaps."""
    out = spans[0]["text"]
    for prev, cur in zip(spans, spans[1:]):
        gap = cur["bbox"][0] - prev["bbox"][2]
        if gap > 1 and not out.endswith(" ") and not cur["text"].startswith(" "):
            out += " "
        out += cur["text"]
    return out


def parse_program(doc: pymupdf.Document) -> list[dict]:
    lines = []  # (text, kind) with kind in {"bold", "mixed", "plain"}
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip() and "Wingdings" not in s["font"]]
                # A line of only small text is a page footer; small text in a
                # body-size line is a subscript or superscript (CO2, 1H NMR).
                body = [s for s in spans if s["size"] >= MIN_BODY_SIZE]
                if not body or RUNNING_HEADER.fullmatch(join_spans(spans)):
                    continue
                bold = [bool(s["flags"] & BOLD) for s in body]
                kind = "bold" if all(bold) else "mixed" if any(bold) else "plain"
                lines.append((join_spans(spans), kind))

    entries = []
    i = 0
    while i < len(lines):
        if not lines[i][0].lstrip().startswith("Faculty Advisor"):
            i += 1
            continue
        advisor = ADVISOR.search(lines[i][0]).group(1)
        # Presenter: the bold line just before the advisor, plus earlier bold
        # lines when the name list wraps ("A, B, and" / "C").
        j = i - 1
        names = [lines[j][0]] if j >= 0 and lines[j][1] == "bold" else []
        while j > 0 and lines[j - 1][1] == "bold" and re.search(r"(,|\band)\s*$", lines[j - 1][0]):
            j -= 1
            names.insert(0, lines[j][0])
        i += 1
        title = []
        while i < len(lines) and lines[i][1] != "plain" and not lines[i][0].lstrip().startswith("Faculty Advisor"):
            title.append(lines[i][0])
            i += 1
        body = []
        # The abstract ends at the next all-bold line: a presenter or a heading.
        while i < len(lines) and lines[i][1] != "bold":
            body.append(lines[i][0])
            i += 1
        e = entry(split_people("\n".join(names), last_first=False), text(advisor), text("\n".join(title)), text("\n".join(body)))
        if e:
            entries.append(e)
    return entries


def parse_guide(doc: pymupdf.Document, last_first: bool) -> list[dict]:
    blocks = [b[4] for page in doc for b in page.get_text("blocks") if b[4].strip()]
    entries = []
    current: list[str] = []
    for b in blocks:
        if not b.lstrip().startswith(GUIDE_END):
            current.append(b)
            continue
        # Anchor the header on the advisor line so front matter before the
        # first entry is skipped. The advisor may share the presenter block or
        # sit in its own block right after it.
        start, end = 0, 1
        for j, c in enumerate(current):
            if "Faculty Advisor" in c:
                start = j - 1 if c.lstrip().startswith("Faculty Advisor") and j > 0 else j
                end = j + 1
                break
        header = "\n".join(current[start:end])
        advisor = None
        m = ADVISOR.search(header)
        if m:
            advisor = text(m.group(1))
            header = header[: m.start()]
        rest = current[end:]
        if rest:
            e = entry(split_people(header.strip(), last_first), advisor, text(rest[0]), text("\n".join(rest[1:])))
            if e:
                entries.append(e)
        current = []
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached PDFs")
    args = parser.parse_args()

    out = []
    for year in SOURCES:
        doc = pymupdf.open(fetch(year, args.refresh))
        if year in PROGRAM_YEARS:
            entries = parse_program(doc)
        else:
            entries = parse_guide(doc, last_first=year in LAST_FIRST_YEARS)
        for n, e in enumerate(entries, 1):
            out.append({"id": f"expo-{year}-{n:03d}", "year": year, **e, "source": SOURCES[year]})
        print(f"{year}: {len(entries)} abstracts")
    for e in out:
        if e["advisor"]:
            e["advisor"] = affiliations(e["advisor"])

    path = DATA_DIR / "expo_abstracts.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} abstracts to {path}")


if __name__ == "__main__":
    main()
