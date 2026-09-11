"""Minimal EPUB 2/3 container/OPF reader: enough to get the spine, in reading order,
resolved to zip-internal paths, plus core metadata. Not a general-purpose EPUB library."""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass

from lxml import etree

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class SpineItem:
    idref: str
    href: str  # zip-internal path
    media_type: str
    linear: bool
    is_nav: bool


@dataclass
class EpubPackage:
    zip_path: str
    opf_path: str
    identifier: str
    title: str
    language: str
    spine: list[SpineItem]
    # EPUB2-style NCX table of contents, when present (<spine toc="idref">
    # pointing at a manifest item) — EPUB3's own nav document, if any, is
    # already reachable via the spine item with is_nav=True instead.
    ncx_href: str | None = None


class EpubFormatError(ValueError):
    pass


def _resolve(base_dir: str, href: str) -> str:
    """Resolve an OPF-relative href to a zip-internal path."""
    joined = posixpath.normpath(posixpath.join(base_dir, href))
    return joined


def read_package(zip_path: str) -> EpubPackage:
    with zipfile.ZipFile(zip_path) as zf:
        try:
            container = etree.fromstring(zf.read("META-INF/container.xml"))
        except KeyError as exc:
            raise EpubFormatError("missing META-INF/container.xml") from exc

        rootfile = container.find(".//c:rootfile", NS)
        if rootfile is None:
            raise EpubFormatError("container.xml has no <rootfile>")
        opf_path = rootfile.get("full-path")
        if not opf_path:
            raise EpubFormatError("<rootfile> missing full-path")

        opf = etree.fromstring(zf.read(opf_path))
        opf_dir = posixpath.dirname(opf_path)

        manifest: dict[str, tuple[str, str, str]] = {}
        for item in opf.findall(".//opf:manifest/opf:item", NS):
            item_id = item.get("id")
            href = item.get("href")
            media_type = item.get("media-type", "")
            properties = item.get("properties", "")
            if item_id and href:
                manifest[item_id] = (_resolve(opf_dir, href), media_type, properties)

        spine: list[SpineItem] = []
        for itemref in opf.findall(".//opf:spine/opf:itemref", NS):
            idref = itemref.get("idref")
            if idref not in manifest:
                continue
            href, media_type, properties = manifest[idref]
            linear = itemref.get("linear", "yes") != "no"
            is_nav = "nav" in properties.split()
            spine.append(
                SpineItem(idref=idref, href=href, media_type=media_type, linear=linear, is_nav=is_nav)
            )

        identifier_el = opf.find(".//dc:identifier", NS)
        title_el = opf.find(".//dc:title", NS)
        language_el = opf.find(".//dc:language", NS)

        spine_el = opf.find(".//opf:spine", NS)
        ncx_idref = spine_el.get("toc") if spine_el is not None else None
        ncx_href = manifest[ncx_idref][0] if ncx_idref and ncx_idref in manifest else None

        return EpubPackage(
            zip_path=zip_path,
            opf_path=opf_path,
            identifier=(identifier_el.text or "").strip() if identifier_el is not None else "",
            title=(title_el.text or "").strip() if title_el is not None else "",
            language=(language_el.text or "").strip() if language_el is not None else "und",
            spine=spine,
            ncx_href=ncx_href,
        )


def read_resource(zip_path: str, href: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(href)


def is_xhtml(item: SpineItem) -> bool:
    return item.media_type in ("application/xhtml+xml", "text/html")
