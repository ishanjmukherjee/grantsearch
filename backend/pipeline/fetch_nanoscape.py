"""Download Nanoscape, the undergraduate nanoscience journal, from Arch into data/raw/nanoscape/.

Nanoscape: The Journal for Undergraduate Research in Nanoscience was published
by Northwestern's International Institute for Nanotechnology, 2004-2010, and
took submissions from undergraduates nationwide, so not every author is at
Northwestern. Its 91 papers are a collection in Arch, Northwestern's Hyrax
repository (https://doi.org/10.21985/N2MM8B, collection mg74qm20p):

- collection.html: the collection's listing at 100 per page, from which the 91
  work ids are read, and collection.json, its Hyrax record (which does not
  list member works).
- works/<work id>/work.json: the work's Hyrax metadata (title, creator,
  contributor, description, keyword, subject, date_created, doi,
  bibliographic_citation, license and more); every work has a DOI.
  work.html: the work's page, from which its file set id is read.
- works/<work id>/file_set_<fs>.json: the file set's record, whose label is the
  original file name, and <fs>.pdf, the paper. Each work has one file set,
  and it is a PDF in every case.

date_created by year: 2004 (13), 2005 (12), 2006 (12), 2007 (15), 2008 (15),
2009 (11, one written 2009-06-01), 2010 (11, plus 8049g5125's, written
"20100"). vd66vz98m ("Growth of Cu2O Nanocubes from Seeds in Microwells") has
no date_created; its only date is its 2018 upload.

Arch's load balancer answers 405 (sometimes 403) to downloads after a burst,
so its requests are spaced 20 s apart (download.HOST_GAP), and a refused PDF
pauses the run 10 minutes before it is tried again, up to PAUSES times.

Usage: uv run python -m pipeline.fetch_nanoscape [--refresh]
"""

import argparse
import json
import re
import time

from pipeline.download import RAW, Manifest

SOURCE = "nanoscape"
OUT = RAW / SOURCE
ARCH = "https://arch.library.northwestern.edu"
COLLECTION = "mg74qm20p"
PAUSES = 4
PAUSE = 600


def save_pdf(m: Manifest, rel: str, url: str, refresh: bool, pauses: list[int]) -> None:
    while not m.save(rel, url, refresh=refresh, check=lambda b: b.startswith(b"%PDF")):
        if len(pauses) >= PAUSES:
            raise SystemExit(f"Arch kept refusing {url}; rerun later")
        pauses.append(1)
        print(f"refused; pause {len(pauses)} of {PAUSES}, {PAUSE} s", flush=True)
        time.sleep(PAUSE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch saved files")
    args = parser.parse_args()
    m, pauses = Manifest(SOURCE), []
    try:
        m.save("collection.html", f"{ARCH}/collections/{COLLECTION}?locale=en&per_page=100", refresh=args.refresh)
        m.save("collection.json", f"{ARCH}/collections/{COLLECTION}.json", refresh=args.refresh)
        works = sorted(set(re.findall(r"/concern/generic_works/([a-z0-9]+)", (OUT / "collection.html").read_text())))
        for w in works:
            m.save(f"works/{w}/work.json", f"{ARCH}/concern/generic_works/{w}.json", refresh=args.refresh)
            m.save(f"works/{w}/work.html", f"{ARCH}/concern/generic_works/{w}?locale=en", refresh=args.refresh)
            for fs in sorted(set(re.findall(r"/downloads/([a-z0-9]+)", (OUT / f"works/{w}/work.html").read_text()))):
                m.save(f"works/{w}/file_set_{fs}.json", f"{ARCH}/concern/file_sets/{fs}.json", refresh=args.refresh)
                label = json.loads((OUT / f"works/{w}/file_set_{fs}.json").read_text()).get("label") or ""
                if not label.lower().endswith(".pdf"):
                    raise SystemExit(f"{w}/{fs}: not a PDF ({label!r})")
                save_pdf(m, f"works/{w}/{fs}.pdf", f"{ARCH}/downloads/{fs}", args.refresh, pauses)
        print(f"{len(works)} works")
    finally:
        m.write()


if __name__ == "__main__":
    main()
