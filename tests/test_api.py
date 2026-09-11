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
