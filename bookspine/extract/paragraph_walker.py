"""DOM walk down to paragraph level.

Per the EPUB compatibility checklist: text isn't only inside <p>. li/td/th/dd/
blockquote/figcaption/div/dt/caption are all legal text-bearing containers, and a
<p>-only walker silently drops that content. A leaf is the *innermost* text-bearing
element on its path — e.g. `<li><p>text</p></li>` yields one leaf (the <p>), not two.
"""

from __future__ import annotations

from lxml import etree

from bookspine.models import GuidedNavNode

TEXT_BEARING_TAGS = {"p", "li", "td", "th", "dd", "blockquote", "figcaption", "div", "dt", "caption"}
SECTIONING_TAGS = {"section", "article"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "nav"}
EPUB_TYPE_ATTR = "{http://www.idpf.org/2007/ops}type"


def localname(elem: etree._Element) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


def get_text(elem: etree._Element) -> str:
    return " ".join(" ".join(elem.itertext()).split())


def _has_text_bearing_descendant(elem: etree._Element) -> bool:
    for desc in elem.iterdescendants():
        if localname(desc) in TEXT_BEARING_TAGS:
            return True
    return False


def is_leaf_paragraph(elem: etree._Element) -> bool:
    tag = localname(elem)
    if tag not in TEXT_BEARING_TAGS:
        return False
    if not get_text(elem):
        return False
    return not _has_text_bearing_descendant(elem)


LeafRef = tuple[etree._Element, GuidedNavNode, str]  # (element, its GN node, resource href)


def build_document_tree(
    body: etree._Element, href: str, leaves_out: list[LeafRef]
) -> list[GuidedNavNode]:
    """Recurse from a content document's <body>. Returns top-level GN nodes for this
    document. Non-sectioning wrappers (div/ul/ol/table/tbody/tr/li/body itself) are
    transparent: their children splice up rather than adding a "group" node, keeping
    the tree's nesting aligned with the book's actual chapter/section structure."""

    def recurse(elem: etree._Element) -> list[GuidedNavNode]:
        tag = localname(elem)
        if tag in SKIP_TAGS:
            return []

        if is_leaf_paragraph(elem):
            node = GuidedNavNode(role="paragraph", text=get_text(elem))
            leaves_out.append((elem, node, href))
            return [node]

        heading_text: str | None = None
        child_nodes: list[GuidedNavNode] = []
        for child in elem:
            if not isinstance(child.tag, str):
                continue  # comments / processing instructions
            ctag = localname(child)
            if ctag in HEADING_TAGS and heading_text is None:
                heading_text = get_text(child)
                continue
            child_nodes.extend(recurse(child))

        if tag in SECTIONING_TAGS:
            role = elem.get(EPUB_TYPE_ATTR) or tag
            existing_id = elem.get("id")
            node = GuidedNavNode(
                role=role,
                textref=f"{href}#{existing_id}" if existing_id else href,
                text=heading_text,
                children=child_nodes,
            )
            return [node]

        return child_nodes

    return recurse(body)
