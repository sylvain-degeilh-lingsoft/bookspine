"""BookSpine API (§05 of the Reading Assistant Blueprint).

Endpoints:
  POST   /v1/publications                        submit an EPUB for extraction
  GET    /v1/publications/{bookId}                publication record
  GET    /v1/publications/{bookId}/structure      Guided-Navigation-shaped tree
  GET    /v1/publications/{bookId}/paragraphs     paragraph list (id, href, text, locator)
  GET    /v1/resolve/{paragraphId}                the resolver's hot path: id -> Locator
  POST   /v1/publications/{bookId}/reprocess      re-run extraction on a new upload
  GET    /v1/events?since={cursor}                append-only event feed

`paragraphId` is globally unique (minted independently per §05's invariant), so
`/resolve` is flattened to a top-level path rather than nested under `bookId` — a
search hit only ever carries the opaque id, not the book it came from.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from lxml.etree import XMLSyntaxError

from bookspine import service
from bookspine.extract.epub_reader import EpubFormatError
from bookspine.storage import db as db_module
from bookspine.storage import files

logging.basicConfig(level=logging.INFO)

DATA_ROOT = Path(os.environ.get("BOOKSPINE_DATA", "./data"))
DB_PATH = DATA_ROOT / "bookspine.db"
# Same flat layout `bookspine extract -o <dir>` uses (db + publications/ + blobs/
# directly under one root) — so BOOKSPINE_DATA=<dir> and `-o <dir>` are
# interchangeable: point the API at whatever directory the CLI already wrote to.
STORAGE_ROOT = DATA_ROOT
VALID_STRATEGIES = ("id", "selector", "auto")

app = FastAPI(title="BookSpine", version="0.1.0")


def get_conn():
    conn = db_module.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _save_upload(data: bytes) -> Path:
    tmp_dir = STORAGE_ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"upload-{uuid.uuid4().hex}.epub"
    path.write_bytes(data)
    return path


def _run_pipeline(conn, epub_path: Path, strategy: str, notify_url: str | None) -> tuple[dict, bool]:
    try:
        return service.process_epub(conn, str(STORAGE_ROOT), str(epub_path), strategy, notify_url)
    except (EpubFormatError, XMLSyntaxError) as exc:
        raise HTTPException(422, f"could not process EPUB: {exc}") from exc
    finally:
        epub_path.unlink(missing_ok=True)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/publications")
async def create_publication(
    file: UploadFile = File(...),
    strategy: str = Form("auto"),
    notifyUrl: str | None = Form(None),
    conn=Depends(get_conn),
):
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {VALID_STRATEGIES}")
    epub_path = _save_upload(await file.read())
    record, unchanged = _run_pipeline(conn, epub_path, strategy, notifyUrl)
    return JSONResponse(record, status_code=200 if unchanged else 201)


@app.get("/v1/publications/{book_id}")
def get_publication(book_id: str, conn=Depends(get_conn)):
    record = db_module.get_publication(conn, book_id)
    if record is None:
        raise HTTPException(404, "publication not found")
    return record


@app.get("/v1/publications/{book_id}/structure")
def get_structure(book_id: str, conn=Depends(get_conn)):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    path = files.publication_dir(STORAGE_ROOT, book_id) / "structure.json"
    return files.read_json(path)


@app.get("/v1/publications/{book_id}/paragraphs")
def get_paragraphs(book_id: str, conn=Depends(get_conn)):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    return {"bookId": book_id, "paragraphs": db_module.list_paragraphs(conn, book_id)}


@app.get("/v1/resolve/{paragraph_id}")
def resolve(paragraph_id: str, conn=Depends(get_conn)):
    para = db_module.get_paragraph(conn, paragraph_id)
    if para is None:
        raise HTTPException(404, "paragraph not found")
    return {**para["locator"], "paragraphId": para["paragraphId"], "bookId": para["bookId"]}


@app.post("/v1/publications/{book_id}/reprocess")
async def reprocess(
    book_id: str,
    file: UploadFile = File(...),
    strategy: str = Form("auto"),
    notifyUrl: str | None = Form(None),
    conn=Depends(get_conn),
):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {VALID_STRATEGIES}")
    epub_path = _save_upload(await file.read())
    record, unchanged = _run_pipeline(conn, epub_path, strategy, notifyUrl)
    if record["bookId"] != book_id:
        raise HTTPException(409, f"uploaded file resolves to bookId {record['bookId']}, not {book_id}")
    return JSONResponse({**record, "unchanged": unchanged}, status_code=200)


@app.get("/v1/events")
def get_events(since: int = Query(0), conn=Depends(get_conn)):
    events = db_module.list_events(conn, since)
    next_cursor = events[-1]["cursor"] if events else since
    return {"events": events, "nextCursor": next_cursor}
