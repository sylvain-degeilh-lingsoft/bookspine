"""Unpacks an EPUB into harness/public/book/ and writes a manifest.json next to it,
so Vite can serve it as a plain static Readium Web Publication Manifest for
@readium/navigator's EpubNavigator + HttpFetcher — the same shape a real
publication server would serve, just pre-baked to a folder instead of generated
on the fly.

Also writes the same files to harness/public/books/{bookId}/, a stable
per-book path keyed by the same bookId BookSpine's own /v1/publications
returns. The bookspine-search-panel POC needs this: its book picker can only
switch which book Thorium Web actually *renders* by navigating to a different
manifest URL (a page's Publication is bound to whatever manifest it was
opened with — nothing a panel inside that page can change in place), and it
needs that URL to be independent of whatever was most recently unpacked to
the single fixed public/book/ path.

Usage: python prepare_book.py <path-to.epub>
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import sys
import zipfile
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bookspine.extract.epub_reader import read_package, read_resource  # noqa: E402
from bookspine.extract.pipeline import mint_book_id  # noqa: E402

HARNESS_ROOT = Path(__file__).resolve().parent
BOOK_DIR = HARNESS_ROOT / "public" / "book"
BOOKS_DIR = HARNESS_ROOT / "public" / "books"

# Readium's own convention (readium/architecture's pagination.md extension):
# roughly one position per ~1024 characters of visible text.
CHARS_PER_POSITION = 1024

EPUB_OPS_NS = "http://www.idpf.org/2007/ops"


def _visible_text_length(html_bytes: bytes) -> int:
    text = html_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text)


def _local_tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _parse_toc_list(ol_el, nav_dir: str) -> list[dict]:
    entries = []
    for li in ol_el:
        if _local_tag(li) != "li":
            continue
        link_el = None
        child_ol = None
        for child in li:
            tag = _local_tag(child)
            if tag in ("a", "span") and link_el is None:
                link_el = child
            elif tag == "ol":
                child_ol = child
        if link_el is None:
            continue
        title = "".join(link_el.itertext()).strip()
        if not title:
            continue
        entry: dict = {"title": title}
        href = link_el.get("href")
        if href:
            entry["href"] = href if href.startswith("#") else posixpath.normpath(posixpath.join(nav_dir, href))
        if child_ol is not None:
            children = _parse_toc_list(child_ol, nav_dir)
            if children:
                entry["children"] = children
        entries.append(entry)
    return entries


def _parse_ncx_navpoints(parent_el, ncx_dir: str) -> list[dict]:
    entries = []
    for nav_point in parent_el:
        if _local_tag(nav_point) != "navPoint":
            continue
        label = next((el for el in nav_point if _local_tag(el) == "navLabel"), None)
        content = next((el for el in nav_point if _local_tag(el) == "content"), None)
        if label is None or content is None:
            continue
        text_el = next((el for el in label if _local_tag(el) == "text"), None)
        title = "".join(text_el.itertext()).strip() if text_el is not None else ""
        src = content.get("src")
        if not title or not src:
            continue
        entry: dict = {
            "title": title,
            "href": src if src.startswith("#") else posixpath.normpath(posixpath.join(ncx_dir, src)),
        }
        children = _parse_ncx_navpoints(nav_point, ncx_dir)
        if children:
            entry["children"] = children
        entries.append(entry)
    return entries


def parse_toc(epub_path: Path, pkg) -> list[dict]:
    """Parses the real chapter titles out of the EPUB's own table of contents
    — the EPUB3 navigation document (<nav epub:type="toc">) if there is one,
    else the EPUB2 NCX (<spine toc="...">) — rather than leaving `toc` out of
    the manifest, which makes Thorium Web fall back to numbering readingOrder
    entries "{title} 1", "{title} 2", ... instead of showing real chapter
    names. Returns [] (matching "no ToC provided") if neither is present."""
    nav_item = next((item for item in pkg.spine if item.is_nav), None)
    if nav_item is not None:
        root = etree.fromstring(read_resource(str(epub_path), nav_item.href))
        toc_nav = next(
            (el for el in root.iter() if _local_tag(el) == "nav" and el.get(f"{{{EPUB_OPS_NS}}}type") == "toc"),
            None,
        )
        ol = next((el for el in toc_nav.iter() if _local_tag(el) == "ol"), None) if toc_nav is not None else None
        if ol is not None:
            toc = _parse_toc_list(ol, posixpath.dirname(nav_item.href))
            if toc:
                return toc

    if pkg.ncx_href:
        root = etree.fromstring(read_resource(str(epub_path), pkg.ncx_href))
        nav_map = next((el for el in root.iter() if _local_tag(el) == "navMap"), None)
        if nav_map is not None:
            return _parse_ncx_navpoints(nav_map, posixpath.dirname(pkg.ncx_href))

    return []


def build_manifest(pkg, toc: list[dict]) -> dict:
    reading_order = [
        {"href": item.href, "type": item.media_type}
        for item in pkg.spine
        if item.linear and not item.is_nav
    ]
    manifest = {
        "@context": "https://readium.org/webpub-manifest/context.jsonld",
        "metadata": {
            "title": pkg.title or pkg.identifier,
            "identifier": pkg.identifier,
            "language": pkg.language,
            # Without this, Thorium Web's detectProfile() falls back to its generic
            # "webPub" profile/navigator instead of the EPUB one, since it has no
            # other way to tell the two apart from a bare manifest.
            "conformsTo": "https://readium.org/webpub-manifest/profiles/epub",
        },
        "links": [
            {"rel": "self", "href": "manifest.json", "type": "application/webpub+json"},
            {
                "rel": "http://readium.org/positions",
                "href": "positions.json",
                "type": "application/vnd.readium.position-list+json",
            },
        ],
        "readingOrder": reading_order,
    }
    if toc:
        manifest["toc"] = toc
    return manifest


def build_positions(epub_path: Path, reading_order: list[dict]) -> dict:
    """A real Position List (readium/architecture's pagination.md extension):
    ~1 position per CHARS_PER_POSITION characters of each resource's visible
    text, not just one per resource — @readium/navigator's own internal
    progression tracking (EpubNavigator.syncLocation -> findNearestPositions,
    which runs continuously as the reader scrolls/paginates, independent of
    any explicit navigation) expects this granularity. A one-position-per-file
    list is dense enough for EpubNavigator.go()'s href lookup (which is all
    the earlier, cruder version of this function was written for) but starves
    that internal tracking, which can then compute a position past the end of
    the list at a resource boundary — surfacing as "Locator not found in
    position list: N > total" with no explicit navigation action to blame."""
    lengths = [max(_visible_text_length(read_resource(str(epub_path), item["href"])), 1) for item in reading_order]
    total_chars = sum(lengths)

    positions: list[dict] = []
    chars_before = 0
    for item, length in zip(reading_order, lengths):
        chunk_count = max(1, round(length / CHARS_PER_POSITION))
        for i in range(chunk_count):
            positions.append({
                "href": item["href"],
                "type": item["type"],
                "locations": {
                    "position": len(positions) + 1,
                    "progression": i / chunk_count,
                    "totalProgression": (chars_before + i * length / chunk_count) / total_chars,
                },
            })
        chars_before += length

    return {"total": len(positions), "positions": positions}


def _write_book(dest_dir: Path, epub_path: Path, pkg, manifest: dict, positions: dict) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)

    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(dest_dir)

    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (dest_dir / "positions.json").write_text(json.dumps(positions, indent=2), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python prepare_book.py <path-to.epub>", file=sys.stderr)
        raise SystemExit(1)

    epub_path = Path(sys.argv[1]).resolve()
    if not epub_path.is_file():
        print(f"not a file: {epub_path}", file=sys.stderr)
        raise SystemExit(1)

    pkg = read_package(str(epub_path))
    book_id = mint_book_id(pkg.identifier)

    toc = parse_toc(epub_path, pkg)
    manifest = build_manifest(pkg, toc)
    positions = build_positions(epub_path, manifest["readingOrder"])

    _write_book(BOOK_DIR, epub_path, pkg, manifest, positions)
    book_dir = BOOKS_DIR / book_id
    _write_book(book_dir, epub_path, pkg, manifest, positions)

    print(f"Unpacked {epub_path.name} -> {BOOK_DIR} and {book_dir}")
    print(f"  bookId: {book_id!r}")
    print(f"  identifier: {pkg.identifier!r}")
    print(f"  readingOrder: {len(manifest['readingOrder'])} resources")
    print(f"  toc entries: {len(toc)}")
    print(f"  positions: {positions['total']}")
    print("Now run: npm run dev  (inside harness/)")


if __name__ == "__main__":
    main()
