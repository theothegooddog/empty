#!/usr/bin/env python3
"""partfile - a manifest format for rebuilding a file from pieces found online.

A `.parts` manifest is a small JSON file that describes a target file as a
list of fixed-size chunks, each identified by its SHA-256 hash, together with
places on the internet the bytes can be fetched from. Given a manifest (or a
file name that an index maps to a manifest), `partfile get` downloads every
chunk from whichever source has it, verifies each one against its hash, and
writes the reassembled file. Because every chunk is hash-checked, sources do
not need to be trusted - a bad or tampered mirror is simply skipped.

Usage:
    partfile.py create FILE --url URL [--url URL ...] [--chunk-size N] [-o OUT]
    partfile.py get NAME_OR_MANIFEST [--index URL_OR_PATH ...] [-o OUT] [-j N]
    partfile.py info MANIFEST

Manifest layout (format "partfile/1"):
    {
      "format": "partfile/1",
      "name": "example.iso",
      "size": 123456789,
      "sha256": "<hash of the whole file>",
      "chunk_size": 4194304,
      "sources": ["https://mirror-a/example.iso", ...],   # whole-file URLs, fetched with HTTP Range
      "chunks": [
        {"offset": 0, "size": 4194304, "sha256": "...",
         "urls": ["https://cdn/chunk0.bin"]},              # optional per-chunk URLs
        ...
      ]
    }

Index layout (maps file names to manifests, so you can ask for a file by name):
    {"files": {"example.iso": "https://host/example.iso.parts", ...}}
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import sys
import urllib.parse
import urllib.request

FORMAT = "partfile/1"
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
USER_AGENT = "partfile/1.0"
TIMEOUT = 30


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_url(s: str) -> bool:
    return urllib.parse.urlparse(s).scheme in ("http", "https", "file")


def read_location(location: str) -> bytes:
    """Read a manifest or index from a URL or a local path."""
    if is_url(location):
        req = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    with open(location, "rb") as f:
        return f.read()


# --------------------------------------------------------------------------
# create


def create_manifest(path: str, urls: list[str], chunk_size: int) -> dict:
    whole = hashlib.sha256()
    chunks = []
    offset = 0
    with open(path, "rb") as f:
        while block := f.read(chunk_size):
            whole.update(block)
            chunks.append({"offset": offset, "size": len(block), "sha256": sha256(block)})
            offset += len(block)
    return {
        "format": FORMAT,
        "name": os.path.basename(path),
        "size": offset,
        "sha256": whole.hexdigest(),
        "chunk_size": chunk_size,
        "sources": urls,
        "chunks": chunks,
    }


# --------------------------------------------------------------------------
# get


def validate_manifest(m: dict) -> None:
    if m.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} manifest (format={m.get('format')!r})")
    expected = 0
    for c in m["chunks"]:
        if c["offset"] != expected:
            raise ValueError(f"chunk at offset {c['offset']} leaves a gap/overlap")
        expected += c["size"]
    if expected != m["size"]:
        raise ValueError("chunk sizes do not add up to the file size")


def resolve(name_or_manifest: str, indexes: list[str]) -> dict:
    """Turn a manifest path/URL, or a bare file name looked up in indexes, into a manifest."""
    if is_url(name_or_manifest) or os.path.exists(name_or_manifest):
        return json.loads(read_location(name_or_manifest))
    for index in indexes:
        try:
            files = json.loads(read_location(index)).get("files", {})
        except Exception as e:  # noqa: BLE001 - an unreachable index is not fatal
            print(f"  index {index}: unavailable ({e})", file=sys.stderr)
            continue
        if name_or_manifest in files:
            loc = files[name_or_manifest]
            if not is_url(loc) and not is_url(index):
                loc = os.path.join(os.path.dirname(index), loc)
            elif not is_url(loc):
                loc = urllib.parse.urljoin(index, loc)
            print(f"found {name_or_manifest!r} in {index}")
            return json.loads(read_location(loc))
    raise LookupError(f"{name_or_manifest!r} is not a manifest and was not found in any index")


def fetch_range(url: str, offset: int, size: int) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": f"bytes={offset}-{offset + size - 1}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status == 206:
            return resp.read(size)
        # Server ignored Range and is sending the whole file: skip to our part.
        remaining = offset
        while remaining:
            skipped = resp.read(min(remaining, 1 << 20))
            if not skipped:
                break
            remaining -= len(skipped)
        return resp.read(size)


def fetch_whole(url: str, size: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(size + 1)


def fetch_chunk(chunk: dict, sources: list[str]) -> tuple[bytes, str]:
    """Try every known location for this chunk; return the first copy whose hash matches."""
    candidates = [("chunk", u) for u in chunk.get("urls", [])]
    shuffled = sources[:]
    random.shuffle(shuffled)  # spread load across mirrors
    candidates += [("range", u) for u in shuffled]
    errors = []
    for kind, url in candidates:
        try:
            if kind == "chunk":
                data = fetch_whole(url, chunk["size"])
            else:
                data = fetch_range(url, chunk["offset"], chunk["size"])
        except Exception as e:  # noqa: BLE001 - try the next source
            errors.append(f"{url}: {e}")
            continue
        if len(data) == chunk["size"] and sha256(data) == chunk["sha256"]:
            return data, url
        errors.append(f"{url}: hash mismatch")
    raise RuntimeError(f"no source had chunk @{chunk['offset']}:\n    " + "\n    ".join(errors))


def get(manifest: dict, out_path: str, jobs: int) -> None:
    validate_manifest(manifest)
    chunks = manifest["chunks"]
    sources = manifest.get("sources", [])
    part_path = out_path + ".partial"

    # Resume: keep any chunks already present and correct in a previous partial download.
    mode = "r+b" if os.path.exists(part_path) else "w+b"
    with open(part_path, mode) as f:
        f.truncate(manifest["size"])
        todo = []
        for c in chunks:
            f.seek(c["offset"])
            if sha256(f.read(c["size"])) != c["sha256"]:
                todo.append(c)
        have = len(chunks) - len(todo)
        if have:
            print(f"resuming: {have}/{len(chunks)} chunks already present")

        done = have
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(fetch_chunk, c, sources): c for c in todo}
            for fut in concurrent.futures.as_completed(futures):
                c = futures[fut]
                data, url = fut.result()
                f.seek(c["offset"])
                f.write(data)
                done += 1
                host = urllib.parse.urlparse(url).netloc or url
                print(f"[{done}/{len(chunks)}] chunk @{c['offset']} from {host}")

        f.seek(0)
        whole = hashlib.sha256()
        while block := f.read(1 << 20):
            whole.update(block)
    if whole.hexdigest() != manifest["sha256"]:
        raise RuntimeError("assembled file does not match the manifest's sha256")
    os.replace(part_path, out_path)
    print(f"done: {out_path} ({manifest['size']} bytes, sha256 verified)")


# --------------------------------------------------------------------------
# cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="make a .parts manifest from a local file")
    c.add_argument("file")
    c.add_argument("--url", action="append", default=[], help="URL where the full file is hosted (repeatable)")
    c.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    c.add_argument("-o", "--output", help="manifest path (default: FILE.parts)")

    g = sub.add_parser("get", help="download and assemble a file from its pieces")
    g.add_argument("target", help="a .parts manifest (path or URL), or a file name to look up in --index")
    g.add_argument("--index", action="append", default=[], help="index of name -> manifest (repeatable)")
    g.add_argument("-o", "--output", help="output path (default: name from the manifest)")
    g.add_argument("-j", "--jobs", type=int, default=4, help="parallel downloads")

    i = sub.add_parser("info", help="describe a manifest")
    i.add_argument("manifest")

    args = p.parse_args(argv)
    try:
        if args.cmd == "create":
            m = create_manifest(args.file, args.url, args.chunk_size)
            out = args.output or args.file + ".parts"
            with open(out, "w") as f:
                json.dump(m, f, indent=2)
            print(f"wrote {out}: {len(m['chunks'])} chunks, {len(m['sources'])} sources")
        elif args.cmd == "get":
            indexes = args.index or os.environ.get("PARTFILE_INDEX", "").split(os.pathsep)
            m = resolve(args.target, [x for x in indexes if x])
            get(m, args.output or os.path.basename(m["name"]), args.jobs)
        elif args.cmd == "info":
            m = json.loads(read_location(args.manifest))
            validate_manifest(m)
            print(f"name:    {m['name']}\nsize:    {m['size']} bytes\nsha256:  {m['sha256']}")
            print(f"chunks:  {len(m['chunks'])} x {m['chunk_size']} bytes")
            print("sources:" + "".join(f"\n  {u}" for u in m.get("sources", [])) or " none")
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
