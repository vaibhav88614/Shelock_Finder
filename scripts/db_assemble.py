"""Reassemble ``data/jobpulse.db`` from the chunks produced by ``db_split.py``.

Reads ``data/db_parts/manifest.json``, concatenates the chunks in order (after
verifying each chunk's sha256), gunzips the result, and verifies the final
file's sha256 against the manifest.

Usage::

    python scripts/db_assemble.py
    python scripts/db_assemble.py --target data/jobpulse.db --force
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

DEFAULT_TARGET = Path("data/jobpulse.db")
DEFAULT_PARTS_DIR = Path("data/db_parts")
MANIFEST_NAME = "manifest.json"
IO_BLOCK = 1 << 20


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(IO_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def assemble_db(target: Path, parts_dir: Path, force: bool = False) -> None:
    manifest_path = parts_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SystemExit(f"error: manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("compression") != "gzip":
        raise SystemExit(
            f"error: unsupported compression {manifest.get('compression')!r}"
        )
    chunks = manifest["chunks"]
    expected_sha256 = manifest["original_sha256"]
    expected_size = manifest["original_size"]

    if target.exists() and not force:
        existing_sha = _sha256_of_file(target)
        if existing_sha == expected_sha256:
            print(f"[db_assemble] {target} already matches manifest; nothing to do")
            return
        raise SystemExit(
            f"error: {target} exists but sha256 differs from manifest "
            f"(got {existing_sha}, expected {expected_sha256}). "
            "Re-run with --force to overwrite."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_gz = parts_dir / "jobpulse.db.gz.tmp"
    print(f"[db_assemble] concatenating {len(chunks)} chunk(s) -> {tmp_gz.name}")
    try:
        with tmp_gz.open("wb") as fout:
            for c in chunks:
                path = parts_dir / c["name"]
                if not path.is_file():
                    raise SystemExit(f"error: missing chunk {path}")
                data = path.read_bytes()
                actual_sha = hashlib.sha256(data).hexdigest()
                if actual_sha != c["sha256"]:
                    raise SystemExit(
                        f"error: chunk {c['name']} sha256 mismatch "
                        f"(expected {c['sha256']}, got {actual_sha})"
                    )
                if len(data) != c["size"]:
                    raise SystemExit(
                        f"error: chunk {c['name']} size mismatch "
                        f"(expected {c['size']}, got {len(data)})"
                    )
                fout.write(data)

        print(f"[db_assemble] decompressing -> {target}")
        with gzip.open(tmp_gz, "rb") as fin, target.open("wb") as fout:
            shutil.copyfileobj(fin, fout, length=IO_BLOCK)
    finally:
        if tmp_gz.exists():
            tmp_gz.unlink()

    actual_size = target.stat().st_size
    actual_sha = _sha256_of_file(target)
    if actual_size != expected_size or actual_sha != expected_sha256:
        raise SystemExit(
            "error: reassembled DB does not match manifest "
            f"(size {actual_size}/{expected_size}, sha256 {actual_sha}/{expected_sha256})"
        )

    print(f"[db_assemble] ok: {target} ({actual_size:,} bytes)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", type=Path, default=DEFAULT_TARGET,
                   help=f"output path for the reassembled DB (default: {DEFAULT_TARGET})")
    p.add_argument("--parts-dir", type=Path, default=DEFAULT_PARTS_DIR,
                   help=f"directory containing chunks + manifest (default: {DEFAULT_PARTS_DIR})")
    p.add_argument("--force", action="store_true",
                   help="overwrite target even if it already exists with a different hash")
    args = p.parse_args(argv)
    assemble_db(args.target, args.parts_dir, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
