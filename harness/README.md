# BookSpine Locator Harness

A minimal test page for checking that BookSpine's Locators actually resolve in a
real Readium reader. It's built directly on `@readium/navigator` +
`@readium/shared` — the same libraries [Thorium Web](https://github.com/edrlab/thorium-web)
itself is built on — rather than on Thorium Web's full reading-app UI, which has
no way to jump to an arbitrary Locator (its own "jump to position" box only
accepts an integer position number, not an href/selector/text Locator).

## Setup

1. Unpack the EPUB you extracted with BookSpine and generate its Readium Web
   Publication Manifest (from the repo root, using the same Python env as
   BookSpine itself):

   ```bash
   python harness/prepare_book.py /path/to/book.epub
   ```

   This also writes a real Position List (`positions.json`) — roughly one
   position per ~1024 characters of each resource's visible text, not just
   one per file — and a real `toc` in `manifest.json`, parsed from the EPUB's
   own EPUB3 nav document or EPUB2 NCX, whichever it has. Both matter beyond
   this harness itself (which only needs enough positions for
   `EpubNavigator.go()`'s href lookup): a real reading app's own internal
   progression tracking runs continuously as it scrolls/paginates, and a
   too-sparse position list can make it compute a position past the end of
   the book at a resource boundary — surfacing as "Locator not found in
   position list" with no explicit navigation action to blame. A missing
   `toc` similarly isn't a hard failure — Thorium Web falls back to
   numbering resources "{title} 1", "{title} 2", ... — but doesn't show real
   chapter names.

2. Install JS dependencies (first run only):

   ```bash
   cd harness
   npm install
   ```

3. Make sure `bookspine serve` is running on port 8080 against the storage
   directory where you extracted that same book — the harness proxies
   `/api/*` to it.

4. Start the harness:

   ```bash
   npm run dev
   ```

   Open the printed URL (typically `http://localhost:5173`).

## Using it

1. Paste the book's `bookId` (e.g. `b_9781449328030`) and click **Load
   paragraphs from BookSpine**.
2. Click any paragraph in the sidebar list — the reader on the right should
   jump straight to it via `EpubNavigator.go(locator, ...)`, the exact call
   Thorium Web's own navigation goes through.
3. Use **Prev / Next** to walk through the list in order, including across
   chapter boundaries.
4. The **Active Locator** panel shows exactly what JSON was sent to `go()`.
   The status line reports whether the navigator resolved it in-page
   (`cssSelector`/`text.highlight`/fragment) or fell back — a fallback logs a
   `[handleLocator]` warning to the browser console with the offending
   Locator.

## Keyword search

This harness's own list only calls `/paragraphs` (the full list) — it has no
search box. BookSpine also exposes:

```
GET /v1/publications/{bookId}/search?q={keyword}&limit={n}
```

a plain case-insensitive substring match over paragraph text (`limit`
defaults to 5, max 50), returning the same `{paragraphId, href, text,
locator}` shape as `/paragraphs`. See the top-level [README](../README.md#api)
for the full endpoint docs. [thorium-panel-poc/](thorium-panel-poc/) wires
this endpoint into a real search panel inside a local Thorium Web clone,
with a jump-to-result action equivalent to what this harness does by hand.

## What this validates (and what it doesn't)

This proves BookSpine's Locators are structurally correct and resolvable by
a real `@readium/navigator` — most usefully, that `locations.cssSelector`
lands where `getCssSelector()` actually looks for it, and that
`text.highlight` narrows all the way down to the paragraph/sentence text.
It does not exercise Thorium Web's own UI chrome (TOC, bookmarks, its
built-in jump-to-position) — just the navigation primitive underneath it.
`thorium-panel-poc/` goes a step further for search specifically, but the
rest of Thorium Web's chrome is still untouched.
