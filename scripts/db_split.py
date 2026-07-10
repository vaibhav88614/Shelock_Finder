"""Split ``data/jobpulse.db`` into git-friendly compressed chunks.

The SQLite database can grow well past GitHub's 100 MB per-file limit, so we
gzip it and slice the compressed stream into fixed-size chunks under
``data/db_parts/``. A ``manifest.json`` records the sha256 of the original
file plus the sha256 of every chunk so ``db_assemble.py`` can verify integrity
end-to-end.

Usage::

    python scripts/db_split.py
    python scripts/db_split.py --source data/jobpulse.db --chunk-size 40MB
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
from pathlib import Path

DEFAULT_SOURCE = Path("data/jobpulse.db")
DEFAULT_PARTS_DIR = Path("data/db_parts")
DEFAULT_CHUNK_SIZE = 45 * 1024 * 1024  # 45 MB, safely under GitHub's 100 MB cap
MANIFEST_NAME = "manifest.json"
CHUNK_PREFIX = "jobpulse.db.gz.part-"
IO_BLOCK = 1 << 20  # 1 MB streaming buffer


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(IO_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def _parse_size(value: str) -> int:
    """Accept ``"45MB"``, ``"45m"``, ``"1_048_576"``, etc."""
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\s*(\d[\d_]*)\s*([kmg]?b?)\s*", value, re.IGNORECASE)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r}")
    n = int(m.group(1).replace("_", ""))
    unit = m.group(2).lower().rstrip("b")
    mult = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[unit]
    return n * mult


def split_db(source: Path, parts_dir: Path, chunk_size: int) -> dict:
    if not source.is_file():
        raise SystemExit(f"error: source database not found: {source}")
    if chunk_size <= 0:
        raise SystemExit("error: --chunk-size must be positive")

    original_size = source.stat().st_size
    print(f"[db_split] source={source} ({original_size:,} bytes)")

    print("[db_split] hashing source...")
    original_sha256 = _sha256_of_file(source)
    print(f"[db_split] sha256={original_sha256}")

    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)

    tmp_gz = parts_dir / "jobpulse.db.gz.tmp"
    print(f"[db_split] compressing (gzip -9) -> {tmp_gz.name}")
    with source.open("rb") as fin, gzip.open(tmp_gz, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout, length=IO_BLOCK)
    compressed_size = tmp_gz.stat().st_size
    ratio = compressed_size / max(original_size, 1)
    print(f"[db_split] compressed={compressed_size:,} bytes ({ratio:.1%} of original)")

    chunks: list[dict] = []
    with tmp_gz.open("rb") as f:
        idx = 0
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            name = f"{CHUNK_PREFIX}{idx:03d}"
            (parts_dir / name).write_bytes(data)
            chunks.append(
                {
                    "name": name,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            print(f"[db_split]   wrote {name} ({len(data):,} bytes)")
            idx += 1

    tmp_gz.unlink()

    manifest = {
        "version": 1,
        "target": source.as_posix(),
        "original_size": original_size,
        "original_sha256": original_sha256,
        "compression": "gzip",
        "compressed_size": compressed_size,
        "chunk_size": chunk_size,
        "chunks": chunks,
    }
    manifest_path = parts_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[db_split] wrote {manifest_path} ({len(chunks)} chunk(s))")
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                   help=f"SQLite DB to split (default: {DEFAULT_SOURCE})")
    p.add_argument("--parts-dir", type=Path, default=DEFAULT_PARTS_DIR,
                   help=f"output directory for chunks (default: {DEFAULT_PARTS_DIR})")
    p.add_argument("--chunk-size", type=_parse_size, default=DEFAULT_CHUNK_SIZE,
                   help="chunk size, e.g. 45MB (default: 45MB)")
    args = p.parse_args(argv)
    split_db(args.source, args.parts_dir, args.chunk_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
