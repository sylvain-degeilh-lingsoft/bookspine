import io
import zipfile

from bookspine import service
from bookspine.storage import db, files
from tests.conftest import CH01_XHTML, build_epub_bytes


def _reopen(tmp_path, name, container_xml, package_opf, nav_xhtml, ch01_xhtml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("EPUB/package.opf", package_opf)
        zf.writestr("EPUB/nav.xhtml", nav_xhtml)
        zf.writestr("EPUB/ch01.xhtml", ch01_xhtml)
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return str(path)


def test_reupload_with_same_source_hash_is_a_noop(tmp_path, sample_epub):
    conn = db.connect(tmp_path / "bookspine.db")
    storage_root = str(tmp_path / "storage")

    record1, unchanged1 = service.process_epub(conn, storage_root, sample_epub, "id")
    assert unchanged1 is False

    record2, unchanged2 = service.process_epub(conn, storage_root, sample_epub, "id")
    assert unchanged2 is True
    assert record2 == record1

    # exactly one "ready" event, not two, since the second call was a no-op
    events = db.list_events(conn, since=0)
    assert len([e for e in events if e["bookId"] == record1["bookId"]]) == 1


def test_reupload_with_different_granularity_is_not_a_noop(tmp_path, sample_epub):
    """Same bytes, but a different granularity requested — real, new work, not the
    idempotent-resubmission case sourceHash-only comparison used to (wrongly) treat
    it as."""
    conn = db.connect(tmp_path / "bookspine.db")
    storage_root = str(tmp_path / "storage")

    record1, unchanged1 = service.process_epub(conn, storage_root, sample_epub, "selector", granularity="paragraph")
    assert unchanged1 is False
    assert record1["granularity"] == "paragraph"

    record2, unchanged2 = service.process_epub(conn, storage_root, sample_epub, "selector", granularity="sentence")
    assert unchanged2 is False
    assert record2["granularity"] == "sentence"
    assert record2["bookId"] == record1["bookId"]
    assert record2["sourceHash"] == record1["sourceHash"]  # same file — only granularity differs


def test_reprocess_archives_previous_paragraph_text(tmp_path):
    from bookspine.extract import pipeline
    from tests.conftest import CONTAINER_XML, NAV_XHTML, PACKAGE_OPF

    conn = db.connect(tmp_path / "bookspine.db")
    storage_root = str(tmp_path / "storage")

    v1 = _reopen(tmp_path, "v1.epub", CONTAINER_XML, PACKAGE_OPF, NAV_XHTML, CH01_XHTML)
    record1, _ = service.process_epub(conn, storage_root, v1, "selector")
    book_id = record1["bookId"]

    edited = CH01_XHTML.replace(b"First paragraph of the chapter.", b"First paragraph, revised.")
    v2 = _reopen(tmp_path, "v2.epub", CONTAINER_XML, PACKAGE_OPF, NAV_XHTML, edited)
    record2, unchanged = service.process_epub(conn, storage_root, v2, "selector")

    assert unchanged is False
    assert record2["bookId"] == book_id
    assert record2["sourceHash"] != record1["sourceHash"]

    prev_texts = {
        r["text"] for r in conn.execute("SELECT text FROM paragraphs_prev WHERE book_id = ?", (book_id,))
    }
    assert "First paragraph of the chapter." in prev_texts

    current_texts = {p["text"] for p in db.list_paragraphs(conn, book_id)}
    assert "First paragraph, revised." in current_texts
    assert "First paragraph of the chapter." not in current_texts


def test_canonical_blob_is_content_addressed(tmp_path, sample_epub):
    conn = db.connect(tmp_path / "bookspine.db")
    storage_root = tmp_path / "storage"

    record, _ = service.process_epub(conn, str(storage_root), sample_epub, "selector")
    blob = files.blob_path(storage_root, record["canonicalHash"])
    assert blob.exists()
    assert blob.read_bytes() == build_epub_bytes()
