"""Scrape the Northwestern Undergraduate Research Journal (NURJ) site.

thenurj.com is WordPress with its REST API open. Fetches every post, page,
category, tag and media item from the API, the home page (whose nav menu
names the editions: page online-vol-11 is "Spring 2025"), and every PDF the
site hosts, and caches them verbatim under data/raw/nurj/. Files hosted
elsewhere (Scribd, Issuu, Google Drive, YouTube) and the site's own images,
audio and video are kept as URLs, not downloaded.

Writes data/nurj.json, which keeps everything the API returns except its
_links (API URLs built from the ids; the raw cache has them):

- menu: the nav menu as a tree of {label, url, page, children}, page being
  the id of the page it opens, if any.
- categories, tags: the API records.
- media: the API records, each with file, the cached copy's path relative to
  data/, for PDFs.
- posts, pages: one record each, with
  - id: nurj-<wp id> for posts, nurj-page-<wp id> for pages
  - wp: the API record, the rendered content HTML included
  - title, categories, tags (names), and attachments (media ids)
  - listed_on: ids of the pages that link to the post or embed one of its
    Scribd documents, and menu: the labels of the menu items opening those
    pages (posts only)
  - blocks: the content as a flat list of headings, text, list items,
    tables, toggle titles, images, embeds and links, in page order. A block's
    text keeps its line breaks; links lists the URLs it links to. Posts built
    with the Divi page builder arrive as unrendered shortcodes; their blocks
    carry divi: {module, column, module_no}, and the URLs and texts that sit
    in shortcode attributes become blocks too. Text a spreadsheet paste left
    in data-sheets-value attributes, when it differs from the text shown, is
    kept as the block's sheet_values. Every word of the content's visible
    text and every URL it references lands in some block; parsing checks this.
  - What the blocks say, read off the site's layouts: people (name, image,
    labels such as Email or Faculty Advisor, bio), labels found outside a
    person's group, sections (heading and text), qa (question and answer
    pairs), and scribd (the embedded Scribd documents, by document id).

Usage: uv run python -m pipeline.scrape_nurj [--refresh]
"""

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR, clean

SITE = "https://thenurj.com"
API = f"{SITE}/wp-json/wp/v2"
ENDPOINTS = ("posts", "pages", "categories", "tags", "media")
NURJ_DIR = RAW_DIR / "nurj"
PER_PAGE = 100

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
LEAVES = {"p", "li", "blockquote", "pre", "figcaption", "dt", "dd", "caption", "address", "summary"}
MEDIA = {"img", "iframe", "video", "audio", "source", "embed", "object"}
SKIP = {"script", "style"}
# Containers whose children are laid out as blocks, not run into the text around them.
CONTAINERS = HEADINGS | LEAVES | MEDIA | {"div", "section", "article", "figure", "ul", "ol", "dl", "table", "header", "footer", "main", "aside", "nav", "details", "form", "center", "noscript", "hr"}

SHORTCODE = re.compile(r"\[(/?)(et_pb_\w+)([^\]]*)\]")
# WordPress curls the quotes inside shortcode attributes: x=”1″ for x="1".
TEXTURIZED = str.maketrans({"“": '"', "”": '"', "″": '"', "‘": "'", "’": "'", "′": "'"})
# Shortcode attributes that hold content, and those that only style or
# configure the layout (a column's type is kept as its blocks' divi.column).
# Parsing raises on any other, so that no new kind of content goes unread.
DIVI_ATTRS = ("title", "title_text", "alt", "button_text", "src", "image", "url", "button_url", "link_option_url", "background_image", "global_module")
DIVI_STYLE = re.compile(
    r"_builder_version|fb_built|type|.*(font|color|padding|margin|width|height|align|spacing|shadow|_last_edited|_tablet|_phone).*"
    r"|background_(repeat|size)|author|comments|featured_image|meta|fullwidth|.*new_window|custom_button|hover_enabled|locked"
    r"|make_equal|saved_tabs|show_bottom_space|module_(id|class)|text_orientation"
)
DIVI_SELF_CLOSING = {"et_pb_line_break_holder"}

LABEL = re.compile(
    r"(?i)\s*(email|e-mail|contact|faculty advis[eo]rs?|advis[eo]rs?|mentors?|subject|majors?|minors?|year|school|doi|by|author|featured|feature|fun fact)\s*:\s*(.*)"
)
SECTION_NAMES = {"bio", "q&a", "abstract", "summary", "bibliography", "references", "works cited", "table of contents", "acknowledgements", "acknowledgments"}
SCRIBD = re.compile(r"scribd\.com/(?:embeds|document|doc)/(\d+)(?:/([^?#]+))?")


def fetch_api(client: httpx.Client, endpoint: str, refresh: bool) -> list[dict]:
    path = NURJ_DIR / f"{endpoint}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    records, page, pages = [], 1, 1
    while page <= pages:
        resp = client.get(f"{API}/{endpoint}", params={"per_page": PER_PAGE, "page": page})
        resp.raise_for_status()
        pages = int(resp.headers["X-WP-TotalPages"])
        records += resp.json()
        page += 1
    # WordPress counts attachments of unpublished posts but does not serve them.
    if len(records) != int(resp.headers["X-WP-Total"]):
        print(f"{endpoint}: the API counts {resp.headers['X-WP-Total']} but serves {len(records)}")
    NURJ_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    return records


def fetch_file(client: httpx.Client, url: str, refresh: bool) -> Path:
    """Cache a file under the site's uploads directory at its path there."""
    path = NURJ_DIR / "files" / urlsplit(url).path.split("/wp-content/uploads/", 1)[1]
    if path.exists() and not refresh:
        return path
    resp = client.get(url)
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def fetch_home(client: httpx.Client, refresh: bool) -> str:
    path = NURJ_DIR / "home.html"
    if path.exists() and not refresh:
        return path.read_text()
    resp = client.get(f"{SITE}/")
    resp.raise_for_status()
    NURJ_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text)
    return resp.text


def fetch_rendered(client: httpx.Client, page: dict, refresh: bool) -> str:
    """A page as the site renders it. Post lists that a page builder widget
    queries at view time appear only here, not in the API's content."""
    path = NURJ_DIR / "rendered" / f"{page['id']}.html"
    if path.exists() and not refresh:
        return path.read_text()
    resp = client.get(page["link"])
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text)
    return resp.text


def listing(rendered: str, page_id: int) -> list[tuple[int, list[str]]]:
    """(post id, category slugs) for each post a rendered page lists, in order;
    each listed post is an <article> classed post-<id> and category-<slug>."""
    out = []
    for el in BeautifulSoup(rendered, "html.parser").find_all("article"):
        classes = el.get("class") or []
        ids = [int(m.group(1)) for k in classes if (m := re.fullmatch(r"post-(\d+)", k))]
        if ids and ids[0] != page_id and "type-page" not in classes and ids[0] not in [i for i, _ in out]:
            out.append((ids[0], [k.removeprefix("category-") for k in classes if k.startswith("category-")]))
    return out


def site_key(url: str) -> str | None:
    """A thenurj.com URL without scheme, www, query or trailing slash, or
    ?p=<id> for a post's short link; None for other sites."""
    parts = urlsplit(url.strip())
    if parts.hostname not in ("thenurj.com", "www.thenurj.com"):
        return None
    if p := parse_qs(parts.query).get("p"):
        return f"?p={p[0]}"
    return parts.path.rstrip("/") or "/"


def text_of(nodes: list) -> str:
    """The text of some nodes, with <br> and block boundaries as line breaks
    and each line cleaned; empty lines dropped."""
    pieces = []

    def visit(n) -> None:
        if isinstance(n, Comment):
            return
        if isinstance(n, NavigableString):
            pieces.append(str(n))
        elif n.name == "br":
            pieces.append("\n")
        elif n.name not in SKIP:
            block = n.name in CONTAINERS
            if block:
                pieces.append("\n")
            for c in n.children:
                visit(c)
            if block:
                pieces.append("\n")

    for n in nodes:
        visit(n)
    lines = (clean(line) for line in "".join(pieces).split("\n"))
    return "\n".join(line for line in lines if line)


def descendants(nodes: list, name: str | set[str]) -> list[Tag]:
    names = {name} if isinstance(name, str) else name
    found = []
    for n in nodes:
        if isinstance(n, Tag):
            if n.name in names:
                found.append(n)
            found += n.find_all(names)
    return found


def sheet_values(nodes: list) -> list[str]:
    """data-sheets-value texts that differ from what the element shows."""
    out = []
    for el in descendants(nodes, "span"):
        if raw := el.get("data-sheets-value"):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {"2": raw}
            v = value.get("2", value.get("3"))
            if v is not None and clean(str(v)) != clean(el.get_text(" ")):
                out.append(str(v))
    return out


def media_block(el: Tag) -> dict | None:
    url = el.get("src") or el.get("data") or el.get("data-src")
    if not url:
        return None
    if el.name == "img":
        b = {"type": "image", "url": url, "alt": el.get("alt") or None, "title": el.get("title") or None}
    else:
        b = {"type": "embed", "tag": el.name, "url": url, "title": el.get("title") or None}
    return {k: v for k, v in b.items() if v is not None}


def text_block(kind: str, nodes: list, **extra) -> list[dict]:
    """A text block for some nodes, then blocks for the media inside them."""
    out = []
    text = text_of(nodes)
    links = [{"text": clean(a.get_text(" ")), "url": a["href"]} for a in descendants(nodes, "a") if a.get("href")]
    if text or links:
        b = {"type": kind, **extra, "text": text}
        if links:
            b["links"] = links
        if sv := sheet_values(nodes):
            b["sheet_values"] = sv
        out.append(b)
    out += [b for el in descendants(nodes, MEDIA) if (b := media_block(el))]
    return out


def html_blocks(fragment: str) -> list[dict]:
    """The blocks of an HTML fragment, in document order."""
    out: list[dict] = []

    def flush(run: list) -> None:
        if run:
            out.extend(text_block("text", run))
            run.clear()

    def walk(el: Tag) -> None:
        run: list = []
        for c in el.children:
            if isinstance(c, Comment):
                continue
            if isinstance(c, NavigableString) or (c.name not in CONTAINERS and not c.find(CONTAINERS)):
                if isinstance(c, Tag) and c.name in SKIP:
                    continue
                run.append(c)
                continue
            flush(run)
            classes = c.get("class") or []
            if any(k.startswith("elementor-tab-title") or k == "elementor-toggle-title" for k in classes):
                out.extend(text_block("toggle", [c]))
            elif c.name in HEADINGS:
                out.extend(text_block("heading", [c], level=int(c.name[1])))
            elif c.name == "li":
                out.extend(text_block("item", [c]) if not c.find(CONTAINERS) else [])
                if c.find(CONTAINERS):
                    walk(c)
            elif c.name in LEAVES:
                out.extend(text_block("text", [c]))
            elif c.name == "table":
                rows = [[text_of([cell]) for cell in tr.find_all(["td", "th"])] for tr in c.find_all("tr")]
                out.append({"type": "table", "rows": rows})
                links = [{"text": clean(a.get_text(" ")), "url": a["href"]} for a in c.find_all("a") if a.get("href")]
                if links:
                    out[-1]["links"] = links
                out.extend(b for m in c.find_all(MEDIA) if (b := media_block(m)))
            elif c.name in MEDIA:
                if b := media_block(c):
                    out.append(b)
                walk(c)
            else:
                # A link around blocks, such as an image linking to its full size.
                if c.name == "a" and c.get("href"):
                    out.append({"type": "link", "text": text_of([c]), "url": c["href"]})
                walk(c)
        flush(run)

    walk(BeautifulSoup(fragment, "html.parser"))
    return out


def divi_blocks(content: str) -> list[dict]:
    """Blocks of content written as Divi shortcodes, tagged with where they sit."""
    out: list[dict] = []
    stack: list[tuple[str, dict, int]] = []  # (module, attributes, module_no)
    module_no = 0
    pos = 0

    def where() -> dict:
        column = next(((a.get("type"), no) for n, a, no in reversed(stack) if n in ("et_pb_column", "et_pb_column_inner")), (None, None))
        return {"module": stack[-1][0] if stack else None, "column": column[0], "column_no": column[1], "module_no": module_no}

    def add(blocks: list[dict]) -> None:
        for b in blocks:
            b["divi"] = where()
            out.append(b)

    for m in SHORTCODE.finditer(content):
        add(html_blocks(content[pos : m.start()]))
        pos = m.end()
        closing, name = m.group(1), m.group(2)
        if closing:
            while stack and stack.pop()[0] != name:
                pass
            continue
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', html.unescape(m.group(3)).translate(TEXTURIZED)))
        if unknown := [k for k in attrs if k not in DIVI_ATTRS and not DIVI_STYLE.fullmatch(k)]:
            raise ValueError(f"unknown {name} attributes {unknown}")
        module_no += 1
        if name not in DIVI_SELF_CLOSING:
            stack.append((name, attrs, module_no))
        info = {k: clean(attrs[k]) for k in DIVI_ATTRS if attrs.get(k, "").strip()}
        if name in ("et_pb_image", "et_pb_fullwidth_image") and "src" in info:
            b = {"type": "image", "url": info.pop("src")}
            b |= {"alt": info.pop("alt")} if "alt" in info else {}
            b |= {"title": info.pop("title_text")} if "title_text" in info else {}
            b |= {"link": info.pop("url")} if "url" in info else {}
            add([b] + ([{"type": "module", "attrs": info}] if info else []))
        elif name == "et_pb_button" and "button_url" in info:
            add([{"type": "link", "text": info.pop("button_text", ""), "url": info.pop("button_url")}] + ([{"type": "module", "attrs": info}] if info else []))
        elif info:
            add([{"type": "module", "attrs": info}])
    add(html_blocks(content[pos:]))
    return out


def visible_words(content: str) -> Counter:
    soup = BeautifulSoup(SHORTCODE.sub("\n", content), "html.parser")
    return Counter(re.findall(r"\w+", text_of([soup]).casefold()))


def block_words(blocks: list[dict]) -> Counter:
    words = Counter()
    for b in blocks:
        if b["type"] in ("text", "heading", "item", "toggle"):
            words.update(re.findall(r"\w+", b["text"].casefold()))
        elif b["type"] == "table":
            words.update(w for row in b["rows"] for cell in row for w in re.findall(r"\w+", cell.casefold()))
    return words


def content_urls(content: str) -> set[str]:
    soup = BeautifulSoup(SHORTCODE.sub("\n", content), "html.parser")
    for el in soup.find_all(SKIP):
        el.decompose()
    return {el[a] for a in ("href", "src", "data") for el in soup.find_all(attrs={a: True}) if el[a].strip()}


def block_urls(blocks: list[dict]) -> set[str]:
    urls = set()
    for b in blocks:
        urls |= {b[k] for k in ("url", "link") if k in b}
        urls |= {link["url"] for link in b.get("links", [])}
    return urls


def content_blocks(content: str) -> list[dict]:
    """The blocks of a post's or page's content; raises if they miss any of its words or URLs."""
    blocks = divi_blocks(content) if SHORTCODE.search(content) else html_blocks(content)
    missing = visible_words(content) - block_words(blocks)
    if missing:
        raise ValueError(f"blocks miss words: {sorted(missing)[:20]}")
    if lost := content_urls(content) - block_urls(blocks):
        raise ValueError(f"blocks miss URLs: {sorted(lost)[:5]}")
    return blocks


def is_text(b: dict) -> bool:
    return b["type"] in ("text", "item")


def label_lines(text: str) -> list[tuple[str, str]] | None:
    """(label, value) for each line of text if every line is a label line, else None."""
    pairs = [(m.group(1), m.group(2).strip()) for line in text.split("\n") if (m := LABEL.fullmatch(line))]
    return pairs if pairs and len(pairs) == len(text.split("\n")) else None


def section_name(b: dict) -> str | None:
    """The heading a block stands for: a heading's or toggle's text, or a
    one-line text block naming a usual section (Divi sets "Abstract" as text)."""
    if b["type"] == "heading":
        return b["text"]
    if b["type"] == "text" and "\n" not in b["text"] and b["text"].casefold().rstrip(":") in SECTION_NAMES:
        return b["text"]
    return None


def person(name: str, image: str | None, rest: list[dict]) -> dict:
    """A person from their name, photo, and the blocks after the name: label lines and bio."""
    p = {"name": name, "labels": [], "bio": []}
    if image:
        p["image"] = image
    if m := LABEL.fullmatch(name):
        p["labels"].append({"label": m.group(1), "value": m.group(2).strip()})
    for b in rest:
        if pairs := label_lines(b["text"]):
            p["labels"] += [{"label": k, "value": v} for k, v in pairs]
        else:
            p["bio"].append(b["text"])
    p["bio"] = "\n\n".join(p["bio"])
    return p


def people(blocks: list[dict], title: str) -> list[dict]:
    """The people a page profiles: a name, then label lines (Email, Faculty
    Advisor, ...) or a BIO heading, then their bio.

    Online volumes set the name as a heading after the photo. Divi posts give
    each person a narrow column holding the photo, then the name as the
    first text module, then label lines and bio."""
    found = []
    columns: dict[int, list[dict]] = {}
    for b in blocks:
        if (d := b.get("divi")) and (m := re.fullmatch(r"(\d+)_(\d+)", d["column"] or "")) and int(m.group(1)) / int(m.group(2)) <= 2 / 5:
            columns.setdefault(d["column_no"], []).append(b)
    for col in columns.values():
        texts = [b for b in col if is_text(b) or b["type"] == "heading"]
        if not texts or not any(b["type"] == "image" for b in col[: col.index(texts[0])]):
            continue
        # Profiles name their subject on a "Featured:" line.
        if (pairs := label_lines(texts[0]["text"])) and pairs[0][0].casefold() not in ("featured", "feature"):
            continue
        image = next(b["url"] for b in col if b["type"] == "image")
        found.append(person(texts[0]["text"], image, texts[1:]))

    for i, b in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if not (
            b["type"] == "heading"
            and not b.get("divi")
            and b["text"].casefold() not in SECTION_NAMES
            and b["text"].casefold() != title.casefold()
            and nxt is not None
            and ((is_text(nxt) and label_lines(nxt["text"])) or (nxt["type"] == "heading" and nxt["text"].casefold() == "bio"))
        ):
            continue
        image = blocks[i - 1]["url"] if i and blocks[i - 1]["type"] == "image" else None
        rest = []
        for x in blocks[i + 1 :]:
            if x["type"] == "image" or (x["type"] in ("heading", "toggle") and x["text"].casefold() != "bio"):
                break
            if is_text(x):
                rest.append(x)
        found.append(person(b["text"], image, rest))
    return found


def sections(blocks: list[dict]) -> list[dict]:
    """The text under each heading (None before the first)."""
    out = [{"heading": None, "text": []}]
    for b in blocks:
        if name := section_name(b):
            out.append({"heading": name, "text": []})
        elif is_text(b) or b["type"] == "toggle":
            out[-1]["text"].append(b["text"])
    return [{"heading": s["heading"], "text": "\n\n".join(s["text"])} for s in out if s["heading"] or s["text"]]


def qa(blocks: list[dict]) -> list[dict]:
    """Question and answer pairs: a toggle title, or a one-line text block ending
    in "?", then the text up to the next question or heading."""
    pairs, open_ = [], False
    for b in blocks:
        if b["type"] == "toggle" or (b["type"] == "text" and "\n" not in b["text"] and b["text"].endswith("?") and len(b["text"]) < 200):
            pairs.append({"question": b["text"], "answer": []})
            open_ = True
        elif b["type"] == "heading":
            open_ = False
        elif is_text(b) and open_:
            pairs[-1]["answer"].append(b["text"])
    return [{"question": p["question"], "answer": "\n\n".join(p["answer"])} for p in pairs if p["answer"]]


def scribd(blocks: list[dict]) -> list[dict]:
    """The Scribd documents the blocks embed or link, by document id."""
    docs: dict[str, dict] = {}
    for b in blocks:
        for url, text in [(b.get("url"), b.get("title")), *((link["url"], link["text"]) for link in b.get("links", []))]:
            if url and (m := SCRIBD.search(url)):
                d = docs.setdefault(m.group(1), {"id": m.group(1)})
                if "/embeds/" in url:
                    d["embed"] = url
                    if key := parse_qs(urlsplit(url).query).get("access_key"):
                        d["access_key"] = key[0]
                    if text:
                        d["embed_title"] = text
                else:
                    d["url"] = url
                    if text:
                        d["link_text"] = text
    return list(docs.values())


def describe(blocks: list[dict], title: str) -> dict:
    found = people(blocks, title)
    taken = {(lab["label"], lab["value"]) for p in found for lab in p["labels"]}
    lines = (LABEL.fullmatch(line) for b in blocks if is_text(b) for line in b["text"].split("\n"))
    labels = [{"label": m.group(1), "value": m.group(2).strip()} for m in lines if m and (m.group(1), m.group(2).strip()) not in taken]
    return {"people": found, "labels": labels, "sections": sections(blocks), "qa": qa(blocks), "scribd": scribd(blocks)}


def menu_tree(home: str, page_by_key: dict[str, int]) -> list[dict]:
    soup = BeautifulSoup(home, "html.parser")
    nav = soup.find("nav")

    def items(ul: Tag) -> list[dict]:
        out = []
        for li in ul.find_all("li", recursive=False):
            a = li.find("a")
            url = a.get("href", "")
            key = site_key(url)
            node = {"label": clean(a.get_text(" ")), "url": url, "page": page_by_key.get(key) if key else None}
            if sub := li.find("ul"):
                node["children"] = items(sub)
            out.append(node)
        return out

    return items(nav.find("ul"))


def flat_menu(tree: list[dict], path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict]]:
    out = []
    for node in tree:
        out.append((path + (node["label"],), node))
        out += flat_menu(node.get("children", []), path + (node["label"],))
    return out


def record(kind: str, wp: dict, names: dict[str, dict[int, str]]) -> dict:
    title = clean(BeautifulSoup(wp["title"]["rendered"], "html.parser").get_text(" "))
    try:
        blocks = content_blocks(wp["content"]["rendered"])
    except ValueError as e:
        raise ValueError(f"{kind} {wp['id']} {wp['link']}: {e}") from None
    r = {
        "id": f"nurj-{wp['id']}" if kind == "post" else f"nurj-page-{wp['id']}",
        "wp": {k: v for k, v in wp.items() if k != "_links"},
        "title": title,
    }
    if kind == "post":
        r["categories"] = [names["categories"][c] for c in wp["categories"]]
        r["tags"] = [names["tags"][t] for t in wp["tags"]]
    return r | {"blocks": blocks} | describe(blocks, title)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached responses and files")
    args = parser.parse_args()

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
        api = {e: fetch_api(client, e, args.refresh) for e in ENDPOINTS}
        home = fetch_home(client, args.refresh)

        names = {e: {x["id"]: html.unescape(x["name"]) for x in api[e]} for e in ("categories", "tags")}
        posts = sorted((record("post", p, names) for p in api["posts"]), key=lambda r: (r["wp"]["date"], r["wp"]["id"]))
        pages = sorted((record("page", p, names) for p in api["pages"]), key=lambda r: (r["wp"]["date"], r["wp"]["id"]))

        pdfs = {m["source_url"] for m in api["media"] if m["mime_type"] == "application/pdf"}
        for r in posts + pages:
            pdfs |= {u for u in block_urls(r["blocks"]) if site_key(u) and "/wp-content/uploads/" in u and urlsplit(u).path.lower().endswith(".pdf")}
        files = {u: str(fetch_file(client, u, args.refresh).relative_to(DATA_DIR)) for u in sorted(pdfs)}
        listings = {p["id"]: listing(fetch_rendered(client, p, args.refresh), p["id"]) for p in api["pages"]}

    page_by_key = {site_key(p["wp"]["link"]): p["wp"]["id"] for p in pages} | {f"?p={p['wp']['id']}": p["wp"]["id"] for p in pages}
    menu = menu_tree(home, page_by_key)
    menu_labels: dict[int, list[str]] = {}
    for path, node in flat_menu(menu):
        if node["page"]:
            menu_labels.setdefault(node["page"], []).append(" > ".join(path))

    # A page's widget lists one category's posts a few at a time; the
    # category shared by every post it shows stands for the whole list.
    for p in pages:
        listed = listings[p["wp"]["id"]]
        p["listing"] = [f"nurj-{i}" for i, _ in listed]
        p["listing_category"] = None
        if listed and len(shared := set.intersection(*(set(c) for _, c in listed))) == 1:
            p["listing_category"] = shared.pop()
    for r in posts:
        keys = {site_key(r["wp"]["link"]), f"?p={r['wp']['id']}"}
        docs = {d["id"] for d in r["scribd"]}
        slugs = {c["slug"] for c in api["categories"] if c["id"] in r["wp"]["categories"]}
        listed = [
            p for p in pages
            if r["id"] in p["listing"]
            or p["listing_category"] in slugs
            or keys & {site_key(u) for u in block_urls(p["blocks"])}
            or docs & {d["id"] for d in p["scribd"]}
        ]
        r["listed_on"] = [p["id"] for p in listed]
        r["menu"] = [label for p in listed for label in menu_labels.get(p["wp"]["id"], [])]
    for r in posts + pages:
        r["attachments"] = [m["id"] for m in api["media"] if m["post"] == r["wp"]["id"]]

    media = [{k: v for k, v in m.items() if k != "_links"} | {"file": files.get(m["source_url"])} for m in api["media"]]
    out = {
        "menu": menu,
        "categories": [{k: v for k, v in c.items() if k != "_links"} for c in api["categories"]],
        "tags": [{k: v for k, v in t.items() if k != "_links"} for t in api["tags"]],
        "media": media,
        "files": files,
        "posts": posts,
        "pages": pages,
    }
    path = DATA_DIR / "nurj.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(posts)} posts, {len(pages)} pages, {len(media)} media items, {len(files)} PDFs -> {path}")
    print(f"{sum(bool(r['people']) for r in posts)} posts profile people, {sum(bool(r['menu']) for r in posts)} are listed in a menu edition")


if __name__ == "__main__":
    main()
