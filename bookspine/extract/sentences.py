"""A deliberately simple sentence splitter — regex boundary detection plus a merge
pass for the two most common false splits (abbreviations, initials). This is a
heuristic, not a real sentence tokenizer: no NLP dependency, so no runtime model
download and no extra weight in the Docker image. Good enough to demonstrate
sentence-level chunking; a production system would likely swap in a real
sentence-boundary library instead."""

from __future__ import annotations

import re

_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+')

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
    "approx", "no", "fig", "eq", "ch", "sec", "vol", "pp", "cf", "al", "co", "inc", "ltd",
}


def _ends_with_abbreviation(fragment: str) -> bool:
    stripped = fragment.rstrip(".!?").rstrip()
    if not stripped:
        return False
    last_word = re.split(r"\s+", stripped)[-1].lower()
    if last_word in _ABBREVIATIONS:
        return True
    return len(last_word) == 1 and last_word.isalpha()  # a bare initial, e.g. "J."


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    sentences: list[str] = []
    buf = ""
    for part in _BOUNDARY_RE.split(text):
        buf = f"{buf} {part}".strip() if buf else part
        if _ends_with_abbreviation(buf):
            continue  # false boundary — keep accumulating into the same sentence
        sentences.append(buf)
        buf = ""
    if buf:
        sentences.append(buf)
    return sentences
