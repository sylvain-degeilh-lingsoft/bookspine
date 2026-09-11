# Thorium Web search panel (reference copy)

A proof of concept showing BookSpine's keyword search wired into a **local
clone of [Thorium Web](https://github.com/edrlab/thorium-web)** as a real,
first-party-style action — same modal/docked capability as its Table of
Contents panel, triggered from the toolbar/overflow menu with its own
keyboard shortcut, jumping to results via the real `EpubNavigator.go()`.

This isn't a working checkout — Thorium Web is a separate, much larger
project (a full Next.js app) that doesn't live inside this repo. These are
copies of the files that changed, kept here purely for reference. To
actually run this, clone `edrlab/thorium-web`, apply these files at the same
relative paths under `src/`, and see the setup notes in
[../README.md](../README.md) for how to point it at a book served by this
harness's `prepare_book.py` + Vite dev server.

## Files

New (all under `src/components/Actions/BookSpineSearch/`):
- `StatefulBookSpineSearchTrigger.tsx` — toolbar/overflow-menu button, modeled on Thorium's own `StatefulTocTrigger`.
- `StatefulBookSpineSearchContainer.tsx` — the panel itself: a book picker (`StatefulDropdown`, the same component Thorium's own settings menus use) fetching `GET /v1/publications` on mount and showing each book's *title*, not its `bookId`; a search form; and a result list, each with a Jump button calling `useEpubNavigator().go()`. Picking a book in the dropdown does a full page navigation to that book's own `.../books/{bookId}/manifest.json` (see below) — a page's `Publication` is bound to whatever manifest it was opened with, so nothing this panel does in place can swap what's actually being *rendered*, only a route change can. The picker's default selection is recovered from that same URL (`currentBookIdFromLocation()`), not from an env var or component state, precisely so the panel's idea of "the current book" can't drift from what's actually on screen — the bug that motivated this design was the search querying one book's index while a different one was being read. On a successful jump it also calls `applyDecorations()` with a single `Highlight`-style decoration for that result's Locator, so the target sentence/paragraph is visibly highlighted in the rendered page — replacing any previous highlight from an earlier jump, so only the just-selected result is ever highlighted. Uses `StatefulSheetWrapper` + `useDocking`, identical machinery to the TOC panel, so it inherits modal (popover/fullscreen by breakpoint) and dock-left/dock-right behavior for free.
- `assets/styles/thorium-web.bookspineSearch.module.css` — styled with the app's own CSS custom properties (`--th-theme-*`, `--th-layout-*`) rather than ad-hoc colors, so it matches Thorium's light/dark themes.
- `index.ts` — barrel export, matching the convention of every other action folder.

New (`src/components/Plugins/helpers/createBookSpineSearchPlugin.ts`):
- A **separate, additive** plugin (`ThPluginRegistry` entry) rather than a change to Thorium's own `createDefaultPlugin.ts` — registered alongside it in `page.tsx`, so nothing about the first-party action set needs to change to add this one.

Modified (small, additive edits — full files kept here for diffing):
- `src/preferences/models/actions.ts` — added `ThActionsKeys.bookspineSearch` and a `defaultBookspineSearchAction` config (copied from `defaultTocAction`'s docking/sheet shape).
- `src/preferences/defaultPreferences.ts` — registered the new key in `actions.reflowOrder`/`fxlOrder` and `actions.keys`.
- `src/app/read/manifest/[manifest]/page.tsx` — passes `plugins={{ epub: () => [createDefaultPlugin(), createBookSpineSearchPlugin()] }}` to `StatefulReaderWrapper` instead of relying on the implicit default-plugin fallback. This also replaces an earlier, cruder iteration of this POC (a fixed overlay `<BookSpineSearchPanel>` mounted outside Thorium's action system entirely — removed once this proper integration worked).
- `src/core/Hooks/Epub/useEpubNavigator.ts` — the hook didn't expose `EpubNavigator.applyDecorations()` at all (only `go`/`goLink`/etc.); added a thin `applyDecorations` wrapper around the same module-scoped `navigatorInstance` singleton every other method already uses, and returned it from the hook.

## What it depends on from BookSpine itself

- `GET /v1/publications` (the book picker) and `GET /v1/publications/{bookId}/search?q=&limit=` (added to `bookspine/api/main.py`).
- CORS enabled on the API (`allow_origins=["*"]`, GET only) so the browser-based reader can call it cross-origin.
- The book must have been unpacked via `../prepare_book.py`, which (as of the version in this repo) writes `manifest.json` (with `metadata.conformsTo` set to the EPUB profile URI) and a real `positions.json` to **two** places: the original single fixed `public/book/` path (unchanged, still what the plain harness itself reads), and a stable per-book `public/books/{bookId}/` path keyed by the same `bookId` `bookspine extract` mints. Both are load-bearing for Thorium Web specifically (its own profile detection and `EpubNavigator.go()` internals depend on them; the harness's own minimal page didn't need either, since it bypasses that machinery) — the per-book path additionally is what lets the search panel's book picker actually switch which book is being read, not just which one `/search` queries.

## Trying a different book

1. Index it with BookSpine so `/search` has data: `bookspine extract /path/to/book.epub --strategy selector --granularity sentence -o ./out` — note the printed `bookId`.
2. Give it a stable per-book manifest URL: `python ../prepare_book.py /path/to/book.epub`. Unlike the single fixed `public/book/` path (which this also still writes, for the plain harness), this book now has its own permanent `public/books/{bookId}/manifest.json` that won't get overwritten by preparing a different book later — so do this once per book, not just for whichever one you're about to read.
3. In Thorium Web, open the search panel and pick the new book by title from the dropdown (populated from `GET /v1/publications`, so a freshly-indexed book shows up on the panel's next mount/reload with no server restart) — this navigates the whole page to that book's manifest URL, so the reader actually switches too, not just the search target.

## Known simplifications

- No i18n: labels are plain English strings, not routed through `useI18n()`/the locale JSON files like every other first-party action's labels are.
- Search is BookSpine's own plain substring match (see `bookspine/storage/db.py`'s `search_paragraphs`) — no ranking or stemming.
- Only the jumped-to result is ever highlighted (one `Highlight`-style decoration, replaced on each jump) — there's no "highlight all matches on this page" mode.
- The dropdown lists every book `/v1/publications` knows about, whether or not `prepare_book.py` was ever run for it — picking one that hasn't gets a 404 on navigation (Thorium's own `ErrorDisplay`), since BookSpine has no notion of "this book also has a servable manifest somewhere."
