"""Replace Git LFS pointer files with their content, for builds without LFS.

Railway's GitHub deploys check out LFS-tracked files as pointers. For each
path given that is a pointer, downloads the object for commit
RAILWAY_GIT_COMMIT_SHA from GitHub's LFS media host (the repo is public) and
checks it against the pointer's sha256 and size. Files that are already real
content are left alone, so local builds download nothing.

Usage: python fetch_lfs.py PATH ...  (PATH relative to the repo root)
"""

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REPO = "ishanjmukherjee/grantsearch"
ROOT = Path(__file__).resolve().parents[1]
POINTER_HEAD = b"version https://git-lfs.github.com/spec/v1\n"


def fetch(path: str) -> None:
    file = ROOT / path
    head = file.read_bytes()[: len(POINTER_HEAD)]
    if head != POINTER_HEAD:
        print(f"{path}: not a pointer, keeping")
        return
    fields = dict(line.split(" ", 1) for line in file.read_text().splitlines())
    oid, size = fields["oid"].removeprefix("sha256:"), int(fields["size"])
    url = f"https://media.githubusercontent.com/media/{REPO}/{os.environ['RAILWAY_GIT_COMMIT_SHA']}/{path}"
    print(f"{path}: downloading {size} bytes from {url}", flush=True)
    data = urllib.request.urlopen(url, timeout=300).read()
    if len(data) != size or hashlib.sha256(data).hexdigest() != oid:
        sys.exit(f"{path}: downloaded content does not match its LFS pointer")
    file.write_bytes(data)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        fetch(path)
