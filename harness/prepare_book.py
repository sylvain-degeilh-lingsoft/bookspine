"""Unpacks an EPUB into harness/public/book/ and writes a manifest.json next to it,
so Vite can serve it as a plain static Readium Web Publication Manifest for
@readium/navigator's EpubNavigator + HttpFetcher — the same shape a real
publication server would serve, just pre-baked to a folder instead of generated
on the fly.

Usage: python prepare_book.py <path-to.epub>
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bookspine.extract.epub_reader import read_package  # noqa: E402

HARNESS_ROOT = Path(__file__).resolve().parent
BOOK_DIR = HARNESS_ROOT / "public" / "book"


def build_manifest(pkg) -> dict:
    reading_order = [
        {"href": item.href, "type": item.media_type}
        for item in pkg.spine
        if item.linear and not item.is_nav
    ]
    return {
        "@context": "https://readium.org/webpub-manifest/context.jsonld",
        "metadata": {
            "title": pkg.title or pkg.identifier,
            "identifier": pkg.identifier,
            "language": pkg.language,
        },
        "links": [
            {"rel": "self", "href": "manifest.json", "type": "application/webpub+json"}
        ],
        "readingOrder": reading_order,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python prepare_book.py <path-to.epub>", file=sys.stderr)
        raise SystemExit(1)

    epub_path = Path(sys.argv[1]).resolve()
    if not epub_path.is_file():
        print(f"not a file: {epub_path}", file=sys.stderr)
        raise SystemExit(1)

    pkg = read_package(str(epub_path))

    if BOOK_DIR.exists():
        shutil.rmtree(BOOK_DIR)
    BOOK_DIR.mkdir(parents=True)

    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(BOOK_DIR)

    manifest = build_manifest(pkg)
    (BOOK_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Unpacked {epub_path.name} -> {BOOK_DIR}")
    print(f"  identifier: {pkg.identifier!r}")
    print(f"  readingOrder: {len(manifest['readingOrder'])} resources")
    print("Now run: npm run dev  (inside harness/)")


if __name__ == "__main__":
    main()
