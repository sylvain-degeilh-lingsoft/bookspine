"""Id-injection vs. CSS-selector addressing (Blueprint §07).

Id-injection is scoped to BookSpine's own paragraph tree / search-and-navigate use
case, on a repackaged copy of the EPUB. CSS-selector (computed while ignoring any
injected attribute — trivial here, since the selector strategy never injects one)
is the portable form used for anything that must resolve against the original,
unmodified file, such as a bookmark or highlight (§07's "Scope of the injected id").
"""

from __future__ import annotations

from lxml import etree

from bookspine.extract.paragraph_walker import LeafRef, localname

ID_PREFIX = "bsp"


def compute_css_selector(elem: etree._Element) -> str:
    """Walk up from `elem` to the nearest ancestor id (or <body>), using
    `tag:nth-of-type(n)` steps. Ignores any BookSpine-injected id by construction:
    this path is only ever taken under the selector strategy, which never injects one."""
    parts: list[str] = []
    node: etree._Element | None = elem
    while node is not None:
        tag = localname(node)
        if tag == "body":
            parts.append("body")
            break
        node_id = node.get("id")
        if node_id:
            parts.append(f"#{node_id}")
            break
        parent = node.getparent()
        if parent is None:
            parts.append(tag)
            break
        siblings = [c for c in parent if isinstance(c.tag, str) and localname(c) == tag]
        index = siblings.index(node) + 1
        parts.append(f"{tag}:nth-of-type({index})")
        node = parent
    parts.reverse()
    return " > ".join(parts)


def apply_id_strategy(leaves: list[LeafRef]) -> list[dict]:
    """Mutates each leaf element in place, assigning it an id if it doesn't already
    have one. Caller is responsible for re-serializing the owning document afterwards."""
    addressing: list[dict] = []
    counter = 1
    for elem, node, href in leaves:
        fragment = elem.get("id")
        if not fragment:
            fragment = f"{ID_PREFIX}-{counter}"
            elem.set("id", fragment)
            counter += 1
        node.textref = f"{href}#{fragment}"
        addressing.append({"fragment": fragment, "css_selector": None})
    return addressing


def apply_selector_strategy(leaves: list[LeafRef]) -> list[dict]:
    """Non-invasive: the source document is never modified."""
    addressing: list[dict] = []
    for elem, node, href in leaves:
        selector = compute_css_selector(elem)
        node.textref = href
        addressing.append({"fragment": elem.get("id"), "css_selector": selector})
    return addressing


def apply_strategy(leaves: list[LeafRef], strategy: str) -> tuple[str, list[dict]]:
    """Returns (resolved_strategy, addressing). `auto` resolves to `selector` —
    it never touches the source file, and the resulting Locators still resolve
    against the reader's own unmodified copy, not just BookSpine's canonical one."""
    resolved = "selector" if strategy == "auto" else strategy
    if resolved == "id":
        return resolved, apply_id_strategy(leaves)
    if resolved == "selector":
        return resolved, apply_selector_strategy(leaves)
    raise ValueError(f"unknown strategy: {strategy}")
