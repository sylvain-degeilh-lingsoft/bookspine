from bookspine.models import GuidedNavNode


def build_publication_tree(per_document_nodes: list[list[GuidedNavNode]]) -> GuidedNavNode:
    """Wrap every content document's top-level nodes under one publication root,
    in reading-order (readium.org/guided-navigation shape)."""
    children: list[GuidedNavNode] = []
    for doc_nodes in per_document_nodes:
        children.extend(doc_nodes)
    return GuidedNavNode(role="publication", children=children)
