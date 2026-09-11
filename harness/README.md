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

## What this validates (and what it doesn't)

This proves BookSpine's Locators are structurally correct and resolvable by
a real `@readium/navigator` — most usefully, that `locations.cssSelector`
lands where `getCssSelector()` actually looks for it, and that
`text.highlight` narrows all the way down to the paragraph/sentence text.
It does not exercise Thorium Web's own UI chrome (search, TOC, bookmarks) —
just the navigation primitive underneath it.
