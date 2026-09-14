# Onboarding

For anyone joining the BookSpine implementation. README.md is the full
CLI/API reference; this is the shorter "how does this fit together and what
must never break" version.

## What this is

BookSpine turns an EPUB into a paragraph-level search index: a structure
tree, one Readium `Locator` per paragraph (keyed by an opaque `paragraphId`),
and a publication record. It's the **processing-service** role in a
three-role architecture (the Reading Assistant Blueprint, §01–§04):

- **Content operator** — holds distribution rights, runs the reading app
  (Thorium Web) and the resolver.
- **Processing service** — BookSpine. Extracts structure, generates
  Locators, keeps the `paragraphId → Locator` resolver current.
- **RAG provider** — a third-party search/embeddings backend.

The one rule everything else follows from: **the RAG provider only ever
sees plain paragraph text and an opaque id.** It never sees the EPUB file,
markup, hrefs, `cssSelector`s, or Locator JSON. A provider's search result
carries a `paragraphId`; turning that back into a navigable Locator is
BookSpine's `/v1/resolve/{paragraphId}` endpoint, called by the content
operator's own plugin — never by the provider directly.

BookSpine itself can run alongside the content operator, as shared
third-party infrastructure, or inside the provider (Blueprint §04's three
deployment models) — today it only exists as a single-container prototype
shaped like the first of those.

## Repo map

| Path | What's there |
|---|---|
| `bookspine/extract/pipeline.py` | Orchestrates one extraction run end to end |
| `bookspine/extract/epub_reader.py` | Unpacks the EPUB, reads the manifest/spine |
| `bookspine/extract/paragraph_walker.py` | Walks the DOM down to paragraph-level leaves |
| `bookspine/extract/strategies.py` | Id-injection vs. CSS-selector addressing (§07) |
| `bookspine/extract/sentences.py` | The `--granularity sentence` splitter |
| `bookspine/extract/guided_nav.py` | Builds the Guided-Navigation structure tree |
| `bookspine/models.py` | `Locator`, `Paragraph`, `PublicationRecord` |
| `bookspine/storage/db.py` | SQLite schema + queries (publications, paragraphs, events) |
| `bookspine/storage/files.py` | Content-addressed blob storage, `publications/{bookId}/` layout |
| `bookspine/service.py` | Glues extraction to persistence; the idempotency/event logic |
| `bookspine/api/main.py` | The HTTP API (FastAPI) — also generates the OpenAPI/Swagger spec |
| `bookspine/cli.py` | `bookspine extract` / `resolve` / `serve` |
| `harness/` | A minimal `@readium/navigator` page for testing Locators against a real reader, independent of Thorium Web |
| `harness/thorium-panel-poc/` | Reference copies of the search panel wired into a local Thorium Web clone |

## Getting started

```bash
python3 -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest                                           # 35 tests, against a synthetic in-memory EPUB fixture

bookspine extract book.epub --strategy id -o ./out
bookspine serve --port 8080
```

Then open `http://localhost:8080/docs` — FastAPI's built-in Swagger UI,
generated from the same route decorators as the code, so it can't drift
from what's actually implemented. `/redoc` and `/openapi.json` are also
live. See README.md's **API** section for a plain curl walkthrough instead.

## Invariants — don't casually change these

- **`paragraphId` is minted independently of addressing.** A UUID or a hash
  of the paragraph's own text — never `hash(href + fragment)` or
  `hash(href + cssSelector)`. An addressing-derived id shifts when a
  sibling paragraph is added or removed elsewhere in the file, silently
  orphaning a provider's embedding even though that paragraph's own text
  never changed (Blueprint §07). This is also why `/v1/resolve` is a flat,
  top-level path rather than nested under `bookId` — `paragraphId` is
  globally unique.
- **Id-injection and CSS-selector addressing serve different consumers.**
  `--strategy id` (default via `auto`) backs BookSpine's own search index —
  safe, because those Locators only ever need to resolve against
  BookSpine's current canonical copy. A bookmark or highlight (not yet
  implemented here) is the opposite: reader-owned, long-lived, and must
  resolve against the *original, unmodified* file too — so it must be
  built from the `selector` strategy's portable fields
  (`cssSelector`, `text.highlight`/`before`/`after`, `progression`,
  `href`/`type`) and must never carry the injected id.
- **Always populate `text.highlight`.** `EpubNavigator.loadLocator()` tries
  it before the selector/id alone, so a publisher edit that shifts
  positional matching but leaves the wording intact still resolves. It's
  the only thing that lets a stale Locator self-heal.
- **EPUB compatibility checklist** (extraction will reject or degrade
  outside this): EPUB 3 preferred (EPUB 2/NCX works with more
  normalization); reflowable, text-bearing XHTML; well-formed markup a DOM
  parser accepts without recovery heuristics; clean, resolvable relative
  hrefs; a usable `dc:identifier` (required — `bookId` is minted from it,
  and a file without one is rejected with a `422`, never silently
  guessed at).
- **PDF is out of scope.** Not "not yet built" — Thorium Web has no PDF
  navigator today, so there's nothing for a PDF Locator to resolve
  against. `format: "pdf"` is accepted (for forward-compatible schema
  shape) but reports `status: "unsupported"`.

## Known simplifications

This is a single-container prototype, not the deployment Blueprint §04
describes. See README.md's **Known simplifications** section for the full
list (no async job queue, no `--retention=ephemeral`, SQLite only, no
auth/multi-tenancy).

## Where to go next

- **README.md** — full CLI/API reference with curl examples.
- **Reading Assistant Blueprint** — the architecture doc this prototype
  implements: the three-role model, the three deployment models, the
  id-injection-vs-selector tradeoff in full, and query-time sequencing.
- **BookSpine API Reference** — a narrative walkthrough of every endpoint
  with request/response examples and the actual error codes.
- **BookSpine Swagger** — the live, interactive spec (same content as
  `/docs`, packaged standalone).
