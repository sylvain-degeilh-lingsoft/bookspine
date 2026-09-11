# BookSpine (prototype)

A working prototype of **BookSpine**, the paragraph-level EPUB structure/Locator
processor sketched in the Reading Assistant Blueprint (§05, with §07's
id-injection-vs-CSS-selector rules and the data-persistence design applied as
described there). It takes an EPUB, walks it down to paragraph level, and produces:

- a **Guided-Navigation-shaped structure tree** (`readium.org/guided-navigation`)
- one **Readium Locator** per paragraph, keyed by an independently-minted, opaque
  `paragraphId`
- a **publication record** (`bookId`, `strategy`, `sourceHash`, `canonicalHash`, ...)

Exposed as both a CLI and a small HTTP API, backed by SQLite, containerized on
Ubuntu 26.04.

This is a prototype for validating the mechanism end-to-end against a real EPUB —
not a production implementation. See **Known simplifications** below for what's
deliberately left out.

## Quickstart (Docker)

```bash
docker compose up --build
```

```bash
curl -F file=@book.epub -F strategy=id http://localhost:8080/v1/publications
```

## Quickstart (local)

```bash
python3 -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest                                            # runs against a synthetic in-memory EPUB fixture

bookspine extract book.epub --strategy id -o ./out
bookspine serve --port 8080
```

## CLI

```
bookspine extract <epub> [--strategy id|selector|auto] [--granularity paragraph|sentence] [-o ./out] [--db ./out/bookspine.db]
bookspine resolve <paragraphId> --db ./out/bookspine.db
bookspine serve [--host 0.0.0.0] [--port 8080]
```

`extract` is idempotent: re-running it with the same file *and* the same
strategy/granularity is a no-op (matched by `sourceHash`), not a reprocess — see
§05/§07. Resubmitting the same file asking for a different strategy or
granularity is real work, not a no-op, and is processed accordingly.

### Granularity: paragraph vs. sentence

`--granularity paragraph` (default) is what's described above: one `paragraphId`
per paragraph-level DOM leaf. `--granularity sentence` splits each paragraph's text
further, minting one independent `paragraphId` per sentence.

This needs no change to addressing at all: a sentence has no DOM node of its own,
so it can't have its own id or `cssSelector` — every sentence Locator carries its
*paragraph's* `fragment`/`cssSelector` unchanged, and only `text.highlight` narrows
down to the sentence itself (with `text.before`/`text.after` now drawn from
neighboring sentences instead of neighboring paragraphs). This is exactly what
`EpubNavigator.go()`'s existing `text.highlight`-based resolution already supports.

In `structure.json`, the paragraph node becomes a container rather than a leaf: it
keeps its full text as a summary and carries no `paragraphId` of its own, with its
sentences nested underneath as the addressable leaves.

Sentence splitting here is a small heuristic (regex boundaries + a merge pass for
common abbreviations and initials) — not a real NLP sentence tokenizer, so no
model-download dependency and no extra weight in the Docker image, but it will
occasionally get an edge case wrong (unusual abbreviations, ellipses, non-English
punctuation conventions).

## API

| Method | Path | |
|---|---|---|
| POST | `/v1/publications` | multipart: `file`, `strategy` (`id`\|`selector`\|`auto`), `granularity` (`paragraph`\|`sentence`), optional `notifyUrl` |
| GET | `/v1/publications/{bookId}` | publication record |
| GET | `/v1/publications/{bookId}/structure` | Guided-Navigation tree |
| GET | `/v1/publications/{bookId}/paragraphs` | paragraph list (id, href, text, Locator) |
| GET | `/v1/resolve/{paragraphId}` | **the resolver's hot path** — `paragraphId` → Locator |
| POST | `/v1/publications/{bookId}/reprocess` | multipart, same fields as create |
| GET | `/v1/events?since={cursor}` | append-only event feed, paged by cursor (recommended — exact) |
| GET | `/v1/events?sinceTime={iso8601}` | same feed, paged by timestamp (convenience — 1s resolution, `createdAt`'s precision) |

```bash
curl -F file=@book.epub -F strategy=id http://localhost:8080/v1/publications
curl http://localhost:8080/v1/publications/b_9781449328030/paragraphs
curl http://localhost:8080/v1/resolve/p_3f9a1c2b7e0d4a11
curl "http://localhost:8080/v1/events?since=0"
```

`paragraphId` is globally unique and minted independently of `href`/fragment (never
`hash(href + fragment)` — see the invariant in the Blueprint/ONBOARDING), so
`/resolve` is a flat top-level path rather than nested under `bookId`: a search hit
only ever carries the opaque id.

## Id-injection vs. CSS-selector (§07)

- `--strategy id` mutates a **copy** of the EPUB, injecting a stable `id` on every
  paragraph-level element that doesn't already have one, and repackages it. This is
  the copy BookSpine indexes and the copy the reader opens for search/navigation.
  `canonicalHash` differs from `sourceHash`.
- `--strategy selector` never touches the file. Each Locator instead carries a
  `cssSelector` computed by walking up to the nearest ancestor id (or `<body>`).
  `canonicalHash` **equals** `sourceHash` — nothing was repackaged.
- `--strategy auto` currently resolves to `id` (the only EPUB-handling path this
  prototype has).

Every Locator also carries `text.highlight` (the paragraph's own text) plus
`text.before`/`text.after` (a few words of surrounding-paragraph context, when the
neighbor is in the same document) — a content-based anchor, self-healing across
re-edits, per §07's rule to always populate it.

**This id-injected copy is not a bookmark format.** A bookmark/highlight must
resolve against the reader's own unmodified file, so it must never carry the
injected id — it needs the `selector` strategy's portable fields instead. This
prototype's extraction pipeline doesn't implement bookmarks; it only demonstrates
that the two addressing strategies coexist and are independently selectable.

## Data persistence (mirrors the Blueprint's §05 subsection)

```
{BOOKSPINE_DATA}/                 (same layout under whatever dir `-o` points the CLI at)
  bookspine.db                    SQLite: publications, paragraphs (resolver index),
                                   paragraphs_prev (previous text, kept across reprocess),
                                   events (append-only, monotonic cursor)
  publications/{bookId}/
    record.json
    structure.json
    paragraphs.jsonl
  blobs/{sha256}.epub              canonical EPUB, content-addressed by canonicalHash —
                                    identical output from two reprocesses shares one file
```

The CLI (`bookspine extract -o <dir>`) and the API (`BOOKSPINE_DATA=<dir> bookspine serve`) use this exact same layout, so pointing both at the same directory means the API immediately sees whatever the CLI already extracted, and vice versa — `bookspine extract` is really just a one-shot, no-server way to drive the same pipeline the API drives per-request.

`paragraphs` is indexed by `paragraph_id` (primary key), so `/resolve` is a lookup,
not a JSONL scan. Reprocessing a book archives its *previous* paragraph text into
`paragraphs_prev` before replacing it — cheap to keep, and it's what a bookmark
re-anchoring flow would diff against.

## Known simplifications

This is a single-container prototype, not the deployment described in Blueprint
§04. In particular, deliberately **not** implemented here:

- No async job queue — `POST /v1/publications` processes synchronously; a real
  deployment would return `status: "processing"` immediately and use the event
  feed / `notifyUrl` webhook to signal completion. `notifyUrl` itself *is* wired up
  (best-effort POST, failures logged and never fail the request).
- No `--retention=ephemeral` flag (Model 3's provider-run deployment) — every
  submitted source file's canonical blob is kept.
- No Postgres option, no LMDB — SQLite only, per the "single-binary deployment"
  half of §05's persistence recommendation.
- No auth, no multi-tenant `bookId` namespacing (§13's Model 2 scenario).
- Guided Navigation `role` values are simplified: sectioning elements (`<section>`,
  `<article>`) use their `epub:type` (or the tag name as a fallback); every other
  wrapper (`div`, `ul`, `li`, `table`, ...) is transparent and splices its children
  up rather than adding a `role: "group"` node. This keeps the tree aligned with
  the book's real chapter/section nesting but is narrower than the full
  Guided Navigation role vocabulary.
- PDF is out of scope (per the Blueprint/ONBOARDING's resolution: Thorium Web has
  no PDF navigator today). `format` is still a stubbed field on the publication
  record for forward compatibility.

## Compatibility

Same checklist as ONBOARDING.md: EPUB 3 preferred, reflowable/text-bearing XHTML,
well-formed markup, resolvable relative hrefs. The paragraph walker treats
`p`, `li`, `td`, `th`, `dd`, `blockquote`, `figcaption`, `div`, `dt`, and `caption`
as text-bearing — not just `<p>` — and always takes the *innermost* qualifying
element on a given path (so `<li><p>...</p></li>` yields one paragraph, not two).

**A usable `dc:identifier` is required.** `bookId` is minted from it (any scheme —
ISBN, UUID, DOI, ...), because `bookId` must stay stable across reprocessing the
same book, and only a real identifier can guarantee that. There's no
content-derived substitute BookSpine could fabricate without risking two
unrelated, identifierless books colliding on the same `bookId`. A file with no
`dc:identifier`, or one that reduces to nothing after stripping non-alphanumeric
characters, is rejected outright (`422` from the API, a clean CLI error) rather
than silently guessed at.
