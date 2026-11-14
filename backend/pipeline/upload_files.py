"""Upload the files Prowl hosts to Cloudflare R2, where https://files.prowl.nu/ serves them.

Every file under data/pdfs/ goes to the R2 bucket BUCKET under its path there,
so data/pdfs/nurj/issuu-2003-2004-03.pdf is served at
https://files.prowl.nu/nurj/issuu-2003-2004-03.pdf. data/pdfs/mmss/ is not in
git: pipeline.mmss_pdfs copies it from the mmss-papers checkout, and has to
have run before --delete, which would otherwise delete those objects. The bucket is public only
through its custom domain, files.prowl.nu (prowl.nu's DNS is on Cloudflare).
Both were set up once with Cloudflare's API, using a token that could also
read the prowl.nu zone and edit its DNS:

    POST /accounts/<account>/r2/buckets {"name": "prowl-files"}
    POST /accounts/<account>/r2/buckets/prowl-files/domains/custom
         {"domain": "files.prowl.nu", "zoneId": "<prowl.nu zone id>", "enabled": true}

A run lists the bucket and uploads the files that are missing from it or whose
MD5 differs from the object's ETag (R2's ETag of a single-part upload is its
MD5), so it uploads only what changed. Objects with no file are listed, and
deleted with --delete. Cloudflare's edge keeps a file for a day
(CACHE_CONTROL), so every file it replaces or deletes is purged from the
prowl.nu zone's cache, which takes the token's cache purge permission too.

It talks to R2's S3-compatible API with an API token from the environment (the
repository's .env): CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, a token
with Workers R2 Storage edit permission. As R2's documentation describes, a
token's S3 access key ID is the token's ID and its secret access key the
SHA-256 of the token.

Usage: uv run --env-file ../.env python -m pipeline.upload_files [--delete] [--dry-run]
"""

import argparse
import hashlib
import mimetypes
import os

import boto3
import httpx
from boto3.s3.transfer import TransferConfig

from pipeline.scrape_surg import DATA_DIR

BUCKET = "prowl-files"
ROOT = DATA_DIR / "pdfs"
PUBLIC = "https://files.prowl.nu/"
CACHE_CONTROL = "public, max-age=86400"
LFS_POINTER = b"version https://git-lfs"
# Upload in one part, whatever the size, so every object's ETag is its MD5.
SINGLE_PART = TransferConfig(multipart_threshold=5 * 1024**3)


def token_id(token: str, account: str) -> str:
    """The API token's ID: a user token verifies at /user/tokens/verify, an
    account-owned one at /accounts/<id>/tokens/verify."""
    for path in ("/user/tokens/verify", f"/accounts/{account}/tokens/verify"):
        r = httpx.get("https://api.cloudflare.com/client/v4" + path, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 200 and r.json().get("success"):
            return r.json()["result"]["id"]
    raise SystemExit("CLOUDFLARE_API_TOKEN did not verify as a user or account token")


def purge(keys: list[str]) -> None:
    """Purge these objects' URLs from the edge cache, 30 to a request (the
    most Cloudflare takes)."""
    headers = {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"}
    api = "https://api.cloudflare.com/client/v4"
    zone = httpx.get(f"{api}/zones", params={"name": "prowl.nu"}, headers=headers, timeout=30).json()["result"][0]["id"]
    for i in range(0, len(keys), 30):
        r = httpx.post(f"{api}/zones/{zone}/purge_cache", json={"files": [PUBLIC + k for k in keys[i : i + 30]]}, headers=headers, timeout=30)
        if not r.json().get("success"):
            raise SystemExit(f"cache purge failed: {r.text}")


def client():
    account, token = os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=token_id(token, account),
        aws_secret_access_key=hashlib.sha256(token.encode()).hexdigest(),
        region_name="auto",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delete", action="store_true", help="delete objects that have no file")
    parser.add_argument("--dry-run", action="store_true", help="only say what would change")
    args = parser.parse_args()
    s3 = client()
    remote = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        remote |= {o["Key"]: o["ETag"].strip('"') for o in page.get("Contents", [])}
    files = sorted(p for p in ROOT.rglob("*") if p.is_file())
    upload = []
    for path in files:
        data = path.read_bytes()
        if data.startswith(LFS_POINTER):
            raise SystemExit(f"{path} is a Git LFS pointer; check out the LFS files first")
        key = path.relative_to(ROOT).as_posix()
        if remote.get(key) != hashlib.md5(data).hexdigest():
            upload.append((key, path))
    stale = sorted(set(remote) - {p.relative_to(ROOT).as_posix() for p in files})
    print(f"{len(files)} files, {len(remote)} objects: {len(upload)} to upload, {len(stale)} with no file")
    if args.dry_run:
        for key, _ in upload:
            print("upload", key)
        for key in stale:
            print("no file", key)
        return
    for key, path in upload:
        s3.upload_file(str(path), BUCKET, key, ExtraArgs={"ContentType": mimetypes.guess_type(key)[0] or "application/octet-stream", "CacheControl": CACHE_CONTROL}, Config=SINGLE_PART)
    for key in stale:
        if args.delete:
            s3.delete_object(Bucket=BUCKET, Key=key)
        print(("deleted " if args.delete else "no file ") + key)
    replaced = [key for key, _ in upload if key in remote] + (stale if args.delete else [])
    if replaced:
        purge(replaced)
        print(f"purged {len(replaced)} from the edge cache")
    if upload:
        print(f"uploaded {len(upload)}; for example {PUBLIC}{upload[0][0]}")


if __name__ == "__main__":
    main()
