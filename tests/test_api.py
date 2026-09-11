import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKSPINE_DATA", str(tmp_path / "data"))
    sys.modules.pop("bookspine.api.main", None)  # re-read BOOKSPINE_DATA on import
    from bookspine.api.main import app

    return TestClient(app)


def _upload(client, epub_path, strategy="id", **extra):
    with open(epub_path, "rb") as f:
        return client.post(
            "/v1/publications",
            files={"file": ("sample.epub", f, "application/epub+zip")},
            data={"strategy": strategy, **extra},
        )


def test_full_roundtrip(client, sample_epub):
    resp = _upload(client, sample_epub)
    assert resp.status_code == 201
    record = resp.json()
    book_id = record["bookId"]
    assert record["strategy"] == "id"

    assert client.get(f"/v1/publications/{book_id}").status_code == 200
    assert client.get("/v1/publications/does-not-exist").status_code == 404

    structure = client.get(f"/v1/publications/{book_id}/structure").json()
    assert structure["role"] == "publication"

    paragraphs = client.get(f"/v1/publications/{book_id}/paragraphs").json()["paragraphs"]
    assert len(paragraphs) == 4
    paragraph_id = paragraphs[0]["paragraphId"]

    resolved = client.get(f"/v1/resolve/{paragraph_id}").json()
    assert resolved["href"] == "EPUB/ch01.xhtml"
    assert resolved["bookId"] == book_id

    assert client.get("/v1/resolve/p_doesnotexist").status_code == 404

    events = client.get("/v1/events").json()
    assert events["events"][0]["type"] == "publication.ready"
    assert events["nextCursor"] >= 1


def test_events_by_timestamp(client, sample_epub):
    _upload(client, sample_epub)

    # everything since the epoch: the one event is there, regardless of tz/format
    resp = client.get("/v1/events", params={"sinceTime": "1970-01-01T00:00:00Z"})
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 1

    created_at = resp.json()["events"][0]["createdAt"]  # "%Y-%m-%dT%H:%M:%SZ"

    # a naive (no-tz) value is treated as UTC, same as the stored createdAt
    naive = created_at.rstrip("Z")
    assert client.get("/v1/events", params={"sinceTime": naive}).json()["events"] == []

    # strictly after the event's own timestamp: nothing new
    resp2 = client.get("/v1/events", params={"sinceTime": created_at})
    assert resp2.json()["events"] == []
    assert resp2.json()["nextCursor"] == 0  # falls back to `since` (default 0): no rows to take a cursor from

    # malformed input is a 400, not a 500 or a silent empty result
    assert client.get("/v1/events", params={"sinceTime": "not-a-date"}).status_code == 400


def test_upload_without_identifier_is_rejected(client, epub_with_no_identifier):
    resp = _upload(client, epub_with_no_identifier)
    assert resp.status_code == 422


def test_sentence_granularity_via_api(client, multi_sentence_epub):
    resp = _upload(client, multi_sentence_epub, strategy="selector", granularity="sentence")
    assert resp.status_code == 201
    record = resp.json()
    assert record["granularity"] == "sentence"

    paragraphs = client.get(f"/v1/publications/{record['bookId']}/paragraphs").json()["paragraphs"]
    assert len(paragraphs) == 6  # 3 sentences from the split paragraph + 3 untouched


def test_invalid_granularity_is_rejected(client, sample_epub):
    resp = _upload(client, sample_epub, granularity="word")
    assert resp.status_code == 400


def test_search_finds_matching_paragraphs(client, sample_epub):
    record = _upload(client, sample_epub).json()
    book_id = record["bookId"]

    resp = client.get(f"/v1/publications/{book_id}/search", params={"q": "chapter"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "chapter"
    assert len(body["results"]) == 1
    assert body["results"][0]["text"] == "First paragraph of the chapter."
    assert "locator" in body["results"][0]

    # case-insensitive
    assert len(client.get(f"/v1/publications/{book_id}/search", params={"q": "CHAPTER"}).json()["results"]) == 1


def test_search_respects_limit(client, sample_epub):
    record = _upload(client, sample_epub).json()
    book_id = record["bookId"]

    # all 4 sample paragraphs contain the word "paragraph"
    resp = client.get(f"/v1/publications/{book_id}/search", params={"q": "paragraph", "limit": 2})
    assert len(resp.json()["results"]) == 2


def test_search_no_match_returns_empty_results(client, sample_epub):
    record = _upload(client, sample_epub).json()
    resp = client.get(f"/v1/publications/{record['bookId']}/search", params={"q": "xyzzy"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_search_unknown_book_is_404(client):
    resp = client.get("/v1/publications/b_doesnotexist/search", params={"q": "chapter"})
    assert resp.status_code == 404


def test_search_missing_query_is_rejected(client, sample_epub):
    record = _upload(client, sample_epub).json()
    resp = client.get(f"/v1/publications/{record['bookId']}/search")
    assert resp.status_code == 422


def test_reupload_is_idempotent(client, sample_epub):
    first = _upload(client, sample_epub)
    assert first.status_code == 201
    second = _upload(client, sample_epub)
    assert second.status_code == 200
    assert second.json() == first.json()


def test_reprocess_wrong_book_id_is_rejected(client, sample_epub, tmp_path):
    _upload(client, sample_epub)
    with open(sample_epub, "rb") as f:
        resp = client.post(
            "/v1/publications/b_totally-different/reprocess",
            files={"file": ("sample.epub", f, "application/epub+zip")},
            data={"strategy": "id"},
        )
    assert resp.status_code == 404  # that bookId was never created
