"""Data shapes for the publication record, the Readium Locator model, and the
Guided Navigation structure tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Strategy = Literal["id", "selector", "auto"]
Granularity = Literal["paragraph", "sentence"]
Status = Literal["processing", "ready", "unsupported", "failed"]


@dataclass
class Locator:
    """Readium Locator, `@readium/shared` shape."""

    href: str
    type: str = "application/xhtml+xml"
    title: str | None = None
    fragment: str | None = None  # HTML id, when the strategy injects/reuses one
    css_selector: str | None = None
    text_before: str | None = None
    text_highlight: str | None = None
    text_after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # cssSelector is an HTML locator extension (readium/architecture's
        # extensions/html.md) and belongs as a direct sibling of `fragments`
        # inside `locations` on the wire. `@readium/shared`'s
        # LocatorLocations.deserialize() only surfaces it via an in-memory
        # `otherLocations` Map built from non-reserved keys — "otherLocations"
        # itself is a reserved key with no meaning in the JSON, so nesting
        # cssSelector under a literal "otherLocations" object (as this used
        # to do) makes it silently unrecoverable by any real Readium reader.
        fragments = [self.fragment] if self.fragment else []
        locations: dict[str, Any] = {}
        if fragments:
            locations["fragments"] = fragments
        if self.css_selector:
            locations["cssSelector"] = self.css_selector
        out: dict[str, Any] = {
            "href": self.href,
            "type": self.type,
            "locations": locations,
        }
        if self.title:
            out["title"] = self.title
        if self.text_highlight:
            out["text"] = {
                "before": self.text_before,
                "highlight": self.text_highlight,
                "after": self.text_after,
            }
        return out


@dataclass
class Paragraph:
    paragraph_id: str
    book_id: str
    href: str
    locator: Locator
    text: str


@dataclass
class GuidedNavNode:
    role: str
    textref: str | None = None
    text: str | None = None
    paragraph_id: str | None = None
    children: list["GuidedNavNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role}
        if self.textref:
            out["textref"] = self.textref
        if self.text:
            out["text"] = self.text
        if self.paragraph_id:
            out["paragraphId"] = self.paragraph_id
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


@dataclass
class PublicationRecord:
    book_id: str
    title: str
    identifier: str
    format: str  # "epub" | "pdf" (stubbed)
    status: Status
    strategy: Strategy
    source_hash: str
    canonical_hash: str
    processed_at: str
    granularity: Granularity = "paragraph"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bookId": self.book_id,
            "title": self.title,
            "identifier": self.identifier,
            "format": self.format,
            "status": self.status,
            "strategy": self.strategy,
            "granularity": self.granularity,
            "canonicalHash": self.canonical_hash,
            "sourceHash": self.source_hash,
            "processedAt": self.processed_at,
        }
