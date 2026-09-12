"""BookSpine API (§05 of the Reading Assistant Blueprint).

Endpoints:
  POST   /v1/publications                        submit an EPUB for extraction
  GET    /v1/publications                        list all publications
  GET    /v1/publications/{bookId}                publication record
  GET    /v1/publications/{bookId}/structure      Guided-Navigation-shaped tree
  GET    /v1/publications/{bookId}/paragraphs     paragraph list (id, href, text, locator)
  GET    /v1/publications/{bookId}/search         keyword search over paragraph text
  GET    /v1/resolve/{paragraphId}                the resolver's hot path: id -> Locator
  POST   /v1/publications/{bookId}/reprocess      re-run extraction on a new upload
  GET    /v1/events?since={cursor}                append-only event feed, by cursor (recommended)
  GET    /v1/events?sinceTime={iso8601}           same feed, by timestamp (coarser: 1s resolution)

`paragraphId` is globally unique (minted independently per §05's invariant), so
`/resolve` is flattened to a top-level path rather than nested under `bookId` — a
search hit only ever carries the opaque id, not the book it came from.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
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
VALID_GRANULARITIES = ("paragraph", "sentence")

app = FastAPI(
    title="BookSpine",
    version="0.1.0",
    description=(
        "Paragraph-level EPUB structure/Locator extraction — the processing-service "
        "role from §05 of the Reading Assistant Blueprint. All read endpoints return "
        "`application/json`; the two write endpoints take `multipart/form-data`. "
        "No auth in this prototype."
    ),
    servers=[{"url": "http://localhost:8080", "description": "bookspine serve (default port)"}],
)

# Prototype only: this lets a browser-based reading app (e.g. a local Thorium Web
# dev instance) call the read endpoints directly cross-origin, with no auth model
# to protect. A real deployment would scope this to known reader origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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


def _run_pipeline(
    conn, epub_path: Path, strategy: str, notify_url: str | None, granularity: str
) -> tuple[dict, bool]:
    try:
        return service.process_epub(conn, str(STORAGE_ROOT), str(epub_path), strategy, notify_url, granularity)
    except (EpubFormatError, XMLSyntaxError) as exc:
        raise HTTPException(422, f"could not process EPUB: {exc}") from exc
    finally:
        epub_path.unlink(missing_ok=True)


@app.get("/healthz", tags=["Health"], summary="Liveness check")
def healthz():
    return {"status": "ok"}


@app.post(
    "/v1/publications",
    tags=["Publications"],
    summary="Submit an EPUB for extraction",
    description=(
        "Runs synchronously — the response is the finished record, not a "
        "`\"processing\"` placeholder. 201 for new work; 200 when the submitted "
        "file's `sourceHash`/`strategy`/`granularity` all match an existing "
        "record (an idempotent no-op, not a reprocess)."
    ),
)
async def create_publication(
    file: UploadFile = File(..., description="The EPUB to process."),
    strategy: str = Form(
        "auto", description="`id` | `selector` | `auto` (Blueprint §07) — `auto` currently resolves to `id`."
    ),
    granularity: str = Form("paragraph", description="`paragraph` | `sentence`."),
    notifyUrl: str | None = Form(
        None,
        description="Best-effort webhook URL, POSTed the finished record once processing completes.",
    ),
    conn=Depends(get_conn),
):
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {VALID_STRATEGIES}")
    if granularity not in VALID_GRANULARITIES:
        raise HTTPException(400, f"granularity must be one of {VALID_GRANULARITIES}")
    epub_path = _save_upload(await file.read())
    record, unchanged = _run_pipeline(conn, epub_path, strategy, notifyUrl, granularity)
    return JSONResponse(record, status_code=200 if unchanged else 201)


@app.get("/v1/publications", tags=["Publications"], summary="List publications")
def list_publications(conn=Depends(get_conn)):
    """Every publication BookSpine has processed, newest first."""
    return {"publications": db_module.list_publications(conn)}


@app.get("/v1/publications/{book_id}", tags=["Publications"], summary="Get a publication record")
def get_publication(book_id: str = PathParam(..., description="From a prior create/list response."), conn=Depends(get_conn)):
    record = db_module.get_publication(conn, book_id)
    if record is None:
        raise HTTPException(404, "publication not found")
    return record


@app.get(
    "/v1/publications/{book_id}/structure",
    tags=["Structure & paragraphs"],
    summary="Get the structure tree",
    description="The Guided-Navigation-shaped structure tree, reusing the book's own chapter/section hierarchy.",
)
def get_structure(book_id: str = PathParam(..., description="From a prior create/list response."), conn=Depends(get_conn)):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    path = files.publication_dir(STORAGE_ROOT, book_id) / "structure.json"
    return files.read_json(path)


@app.get(
    "/v1/publications/{book_id}/paragraphs",
    tags=["Structure & paragraphs"],
    summary="List paragraphs",
    description="The full paragraph list for a book — the pull target for embedding into a RAG provider's index (Blueprint §02).",
)
def get_paragraphs(book_id: str = PathParam(..., description="From a prior create/list response."), conn=Depends(get_conn)):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    return {"bookId": book_id, "paragraphs": db_module.list_paragraphs(conn, book_id)}


@app.get(
    "/v1/publications/{book_id}/search",
    tags=["Structure & paragraphs"],
    summary="Keyword search over paragraph text",
)
def search_paragraphs(
    book_id: str = PathParam(..., description="From a prior create/list response."),
    q: str = Query(..., min_length=1, description="Search text."),
    limit: int = Query(5, ge=1, le=50, description="Max results to return."),
    conn=Depends(get_conn),
):
    """Plain case-insensitive substring match over paragraph text — a prototype
    keyword search, not ranked relevance or stemming."""
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    results = db_module.search_paragraphs(conn, book_id, q, limit)
    return {"bookId": book_id, "query": q, "results": results}


@app.get(
    "/v1/resolve/{paragraph_id}",
    tags=["Resolver"],
    summary="Resolve a paragraphId to a Locator",
    description=(
        "Flat, top-level path — not nested under `bookId` — because `paragraphId` "
        "is minted globally unique (Blueprint §07): a search hit only ever carries "
        "the opaque id, not the book it came from."
    ),
)
def resolve(paragraph_id: str = PathParam(..., description="An id returned by /paragraphs or /search."), conn=Depends(get_conn)):
    para = db_module.get_paragraph(conn, paragraph_id)
    if para is None:
        raise HTTPException(404, "paragraph not found")
    return {**para["locator"], "paragraphId": para["paragraphId"], "bookId": para["bookId"]}


@app.post(
    "/v1/publications/{book_id}/reprocess",
    tags=["Publications"],
    summary="Reprocess a publication",
    description="Re-run extraction on a freshly-uploaded copy of the same book. Same form fields as create.",
)
async def reprocess(
    book_id: str = PathParam(..., description="Must match the bookId the uploaded file itself resolves to."),
    file: UploadFile = File(..., description="The EPUB to process."),
    strategy: str = Form("auto", description="`id` | `selector` | `auto`."),
    granularity: str = Form("paragraph", description="`paragraph` | `sentence`."),
    notifyUrl: str | None = Form(None, description="Best-effort webhook URL for the finished record."),
    conn=Depends(get_conn),
):
    if db_module.get_publication(conn, book_id) is None:
        raise HTTPException(404, "publication not found")
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(400, f"strategy must be one of {VALID_STRATEGIES}")
    if granularity not in VALID_GRANULARITIES:
        raise HTTPException(400, f"granularity must be one of {VALID_GRANULARITIES}")
    epub_path = _save_upload(await file.read())
    record, unchanged = _run_pipeline(conn, epub_path, strategy, notifyUrl, granularity)
    if record["bookId"] != book_id:
        raise HTTPException(409, f"uploaded file resolves to bookId {record['bookId']}, not {book_id}")
    return JSONResponse({**record, "unchanged": unchanged}, status_code=200)


def _normalize_since_time(value: str) -> str:
    """Parses any ISO 8601 datetime (with or without a timezone; naive values are
    assumed UTC) and reformats it to match the exact stored `created_at` format —
    a plain string comparison in SQL only sorts correctly when both sides agree on
    format and precision."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"invalid sinceTime {value!r}: expected ISO 8601") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get(
    "/v1/events",
    tags=["Events"],
    summary="Page through the state-change event feed",
)
def get_events(
    since: int = Query(0, description="Event cursor — the exact, recommended way to page."),
    sinceTime: str | None = Query(
        None, description="ISO 8601 timestamp — convenience alternative, 1s resolution. Wins over `since` if both are given."
    ),
    conn=Depends(get_conn),
):
    """`since` (event cursor) is the recommended, exact way to page through the
    feed. `sinceTime` is a convenience alternative for humans/dashboards — it's
    only as precise as `created_at`'s 1-second resolution, so two events in the
    same second aren't distinguishable by timestamp. If both are given, `sinceTime`
    wins."""
    if sinceTime is not None:
        events = db_module.list_events_since_time(conn, _normalize_since_time(sinceTime))
    else:
        events = db_module.list_events(conn, since)
    next_cursor = events[-1]["cursor"] if events else since
    return {"events": events, "nextCursor": next_cursor}
