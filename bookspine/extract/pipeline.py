"""End-to-end extraction: EPUB in, (PublicationRecord, paragraphs, structure tree,
canonical EPUB bytes) out. Pure function of its input bytes + strategy — no filesystem
or database writes here; callers (CLI, API) own persistence."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from lxml import etree

from bookspine.extract import guided_nav
from bookspine.extract.epub_reader import EpubFormatError, read_package, read_resource
from bookspine.extract.hashing import sha256_hex
from bookspine.extract.paragraph_walker import LeafRef, build_document_tree, localname
from bookspine.extract.repackage import build_canonical_epub
from bookspine.extract.strategies import apply_strategy
from bookspine.models import GuidedNavNode, Locator, Paragraph, PublicationRecord

XML_PARSER = etree.XMLParser(recover=False, resolve_entities=False, no_network=True, huge_tree=True)
CONTEXT_WORDS = 8


def _find_body(root: etree._Element) -> etree._Element | None:
    """Namespace-agnostic <body> lookup — content documents are XHTML with the
    default `http://www.w3.org/1999/xhtml` namespace, but we don't want a hard
    dependency on lxml's `{*}tag` wildcard ElementPath syntax."""
    if localname(root) == "body":
        return root
    for el in root.iter():
        if localname(el) == "body":
            return el
    return None


@dataclass
class ExtractionResult:
    record: PublicationRecord
    paragraphs: list[Paragraph]
    structure: GuidedNavNode
    canonical_epub: bytes


def mint_book_id(identifier: str) -> str:
    """bookId must be stable across reprocessing the same book, which only a real
    dc:identifier can guarantee — there's no content-derived substitute BookSpine
    could fabricate that wouldn't risk colliding two unrelated, identifierless
    books. So an unusable identifier is rejected outright rather than papered over."""
    if not identifier:
        raise EpubFormatError("EPUB has no dc:identifier — cannot mint a stable bookId")
    tail = identifier.rsplit(":", 1)[-1]
    slug = re.sub(r"[^a-zA-Z0-9]+", "", tail)
    if not slug:
        raise EpubFormatError(f"dc:identifier {identifier!r} has no usable characters for a bookId")
    return f"b_{slug}"


def _tail_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[-n:])


def _head_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[:n])


def extract(epub_path: str, strategy: str = "auto") -> ExtractionResult:
    with open(epub_path, "rb") as f:
        source_bytes = f.read()
    source_hash = sha256_hex(source_bytes)

    pkg = read_package(epub_path)
    book_id = mint_book_id(pkg.identifier)

    content_items = [item for item in pkg.spine if item.linear and not item.is_nav]

    leaves: list[LeafRef] = []
    per_document_nodes: list[list[GuidedNavNode]] = []
    parsed_docs: dict[str, etree._Element] = {}

    for item in content_items:
        raw = read_resource(epub_path, item.href)
        root = etree.fromstring(raw, parser=XML_PARSER)
        body = _find_body(root)
        if body is None:
            continue
        per_document_nodes.append(build_document_tree(body, item.href, leaves))
        parsed_docs[item.href] = root

    resolved_strategy, addressing = apply_strategy(leaves, strategy)

    paragraphs: list[Paragraph] = []
    for i, ((elem, node, href), addr) in enumerate(zip(leaves, addressing)):
        paragraph_id = f"p_{uuid.uuid4().hex[:16]}"
        node.paragraph_id = paragraph_id

        text_before = None
        text_after = None
        if i > 0 and leaves[i - 1][2] == href:
            text_before = _tail_words(leaves[i - 1][1].text or "", CONTEXT_WORDS)
        if i + 1 < len(leaves) and leaves[i + 1][2] == href:
            text_after = _head_words(leaves[i + 1][1].text or "", CONTEXT_WORDS)

        locator = Locator(
            href=href,
            fragment=addr["fragment"],
            css_selector=addr["css_selector"],
            text_before=text_before,
            text_highlight=node.text,
            text_after=text_after,
        )
        paragraphs.append(Paragraph(paragraph_id=paragraph_id, book_id=book_id, href=href, locator=locator, text=node.text or ""))

    if resolved_strategy == "id":
        modified_docs = {
            href: etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
            for href, tree in parsed_docs.items()
        }
        canonical_bytes = build_canonical_epub(epub_path, modified_docs)
    else:
        canonical_bytes = source_bytes

    canonical_hash = sha256_hex(canonical_bytes)

    record = PublicationRecord(
        book_id=book_id,
        title=pkg.title,
        identifier=pkg.identifier,
        format="epub",
        status="ready",
        strategy=resolved_strategy,
        source_hash=source_hash,
        canonical_hash=canonical_hash,
        processed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    structure = guided_nav.build_publication_tree(per_document_nodes)

    return ExtractionResult(record=record, paragraphs=paragraphs, structure=structure, canonical_epub=canonical_bytes)
