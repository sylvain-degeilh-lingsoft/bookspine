from bookspine.extract.sentences import split_sentences


def test_basic_split():
    assert split_sentences("First sentence. Second sentence. Third one!") == [
        "First sentence.",
        "Second sentence.",
        "Third one!",
    ]


def test_single_sentence_no_trailing_split():
    assert split_sentences("Just one sentence here.") == ["Just one sentence here."]


def test_empty_and_whitespace():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_abbreviation_does_not_split():
    assert split_sentences("Dr. Smith arrived. He was late.") == [
        "Dr. Smith arrived.",
        "He was late.",
    ]


def test_initial_does_not_split():
    assert split_sentences("J. K. Rowling wrote it. It sold well.") == [
        "J. K. Rowling wrote it.",
        "It sold well.",
    ]


def test_question_and_exclamation_marks():
    assert split_sentences("Is this real? Yes! It is.") == ["Is this real?", "Yes!", "It is."]
