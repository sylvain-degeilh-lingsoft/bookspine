import pytest

from bookspine.extract import pipeline
from bookspine.extract.epub_reader import EpubFormatError

EXPECTED_TEXTS = {
    "First paragraph of the chapter.",
    "A div used directly as a paragraph.",
    "A paragraph inside section A.",
    "List item text wrapped in a paragraph tag.",
}


def test_book_id_minted_from_isbn_identifier(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    assert result.record.book_id == "b_9781234567890"


def test_missing_identifier_is_rejected(epub_with_no_identifier):
    with pytest.raises(EpubFormatError):
        pipeline.extract(epub_with_no_identifier, strategy="selector")


def test_finds_exactly_one_leaf_per_li_p_pair_not_two(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    texts = {p.text for p in result.paragraphs}
    assert texts == EXPECTED_TEXTS
    assert len(result.paragraphs) == 4


def test_selector_strategy_does_not_modify_the_epub(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    assert result.record.strategy == "selector"
    assert result.record.canonical_hash == result.record.source_hash
    for p in result.paragraphs:
        assert p.locator.css_selector
        assert p.locator.fragment is None


def test_selector_paths_land_under_the_right_section(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    by_text = {p.text: p.locator.css_selector for p in result.paragraphs}
    assert by_text["First paragraph of the chapter."].startswith("#ch1")
    assert by_text["A paragraph inside section A."].startswith("#sect-a")
    assert by_text["List item text wrapped in a paragraph tag."].startswith("#sect-a")


def test_id_strategy_injects_ids_and_changes_canonical_hash(sample_epub):
    result = pipeline.extract(sample_epub, strategy="id")
    assert result.record.strategy == "id"
    assert result.record.canonical_hash != result.record.source_hash
    fragments = [p.locator.fragment for p in result.paragraphs]
    assert all(fragments)
    assert len(set(fragments)) == 4  # every leaf gets its own id
    for p in result.paragraphs:
        assert p.locator.css_selector is None


def test_id_strategy_is_deterministic_across_runs(sample_epub):
    a = pipeline.extract(sample_epub, strategy="id")
    b = pipeline.extract(sample_epub, strategy="id")
    assert a.record.canonical_hash == b.record.canonical_hash


def test_paragraph_ids_are_not_derived_from_href_or_fragment(sample_epub):
    result = pipeline.extract(sample_epub, strategy="id")
    for p in result.paragraphs:
        assert p.locator.fragment not in p.paragraph_id
        assert p.href not in p.paragraph_id


def test_structure_tree_shape(sample_epub):
    result = pipeline.extract(sample_epub, strategy="id")
    root = result.structure
    assert root.role == "publication"
    assert len(root.children) == 1  # one content document (nav is excluded)

    chapter = root.children[0]
    assert chapter.role == "chapter"  # from epub:type
    assert chapter.text == "Chapter One"

    section = next(c for c in chapter.children if c.role == "section")
    assert section.text == "Section A"
    leaf_texts = {c.text for c in section.children if c.role == "paragraph"}
    assert leaf_texts == {"A paragraph inside section A.", "List item text wrapped in a paragraph tag."}


def test_text_highlight_always_populated(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    for p in result.paragraphs:
        assert p.locator.text_highlight == p.text


def test_sentence_granularity_splits_within_a_paragraph(multi_sentence_epub):
    result = pipeline.extract(multi_sentence_epub, strategy="selector", granularity="sentence")
    assert result.record.granularity == "sentence"

    # 3 sentences from the split paragraph + 3 untouched single-sentence paragraphs
    assert len(result.paragraphs) == 6
    split_texts = {
        "First sentence of the chapter.",
        "Dr. Smith wrote the second.",
        "A third follows.",
    }
    matching = [p for p in result.paragraphs if p.text in split_texts]
    assert {p.text for p in matching} == split_texts

    # every sentence from the same paragraph shares that paragraph's cssSelector —
    # a sentence has no DOM node of its own to compute a selector from
    assert len({p.locator.css_selector for p in matching}) == 1

    # the paragraph itself becomes a non-addressable container: role stays
    # "paragraph", full text kept as a summary, sentence leaves nested under it
    chapter = result.structure.children[0]
    split_paragraph_node = next(c for c in chapter.children if c.role == "paragraph" and c.children)
    assert split_paragraph_node.paragraph_id is None
    assert split_paragraph_node.text == "First sentence of the chapter. Dr. Smith wrote the second. A third follows."
    assert {c.text for c in split_paragraph_node.children} == split_texts
    assert all(c.role == "sentence" and c.paragraph_id for c in split_paragraph_node.children)


def test_paragraph_granularity_is_the_default(sample_epub):
    result = pipeline.extract(sample_epub, strategy="selector")
    assert result.record.granularity == "paragraph"
