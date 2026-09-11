import { HttpFetcher, Locator, Manifest, Publication } from "@readium/shared";
import { EpubNavigator } from "@readium/navigator";

// Talk to BookSpine directly rather than through Vite's own /api dev proxy:
// that proxy hangs for tens of seconds on responses in the multi-MB range
// (this book's full paragraph list is ~5MB) — a bug in Vite's proxy, not in
// BookSpine or this page. Going direct works because BookSpine's API already
// sends permissive CORS headers (added for the Thorium Web search panel).
const BOOKSPINE_API = "http://localhost:8080";

const statusEl = document.getElementById("status");
const paragraphsEl = document.getElementById("paragraphs");
const locatorJsonEl = document.getElementById("locator-json");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const loadBtn = document.getElementById("load-btn");
const bookSelectEl = document.getElementById("book-select");
const container = document.getElementById("reader-container");

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = kind || "";
}

// --- 0. Which book: an explicit ?book=<bookId> picks prepare_book.py's stable
// per-book path (public/books/{bookId}/); with no query param, fall back to
// the single fixed public/book/ path prepare_book.py also always writes (the
// pre-multi-book default). Either way this determines BOTH which EPUB gets
// rendered and which bookId the paragraph list/search queries — picking a
// book from the dropdown navigates here via a real reload rather than
// swapping state in place, precisely so those two can't drift apart (the bug
// the Thorium Web panel hit before its own book picker did the same thing).

function manifestPathForBook(bookId) {
  return bookId ? `/books/${encodeURIComponent(bookId)}/manifest.json` : "/book/manifest.json";
}

// --- 1. Load the EPUB (unpacked by prepare_book.py) ---

async function loadPublication(manifestPath) {
  const manifestJson = await fetch(manifestPath).then((r) => {
    if (!r.ok) throw new Error(`GET ${manifestPath} -> ${r.status}`);
    return r.json();
  });

  // Manifest.baseURL is derived by stripping the filename off the `self`
  // link's href, so it must be absolute (a relative "manifest.json" strips
  // down to "" and every later Link.toURL(base) call throws "Invalid base
  // URL") — rewrite it to wherever this page actually fetched it from,
  // instead of baking a fixed origin/port into the static manifest file.
  const selfLink = manifestJson.links?.find((l) => l.rel === "self" || (Array.isArray(l.rel) && l.rel.includes("self")));
  if (selfLink) selfLink.href = new URL(manifestPath, location.origin).href;

  const manifest = Manifest.deserialize(manifestJson);
  if (!manifest) throw new Error(`Manifest.deserialize() returned undefined — check ${manifestPath} shape`);

  const baseUrl = new URL(manifestPath, location.origin).href.replace(/manifest\.json$/, "");
  const fetcher = new HttpFetcher(undefined, baseUrl);
  const publication = new Publication({ manifest, fetcher });

  // EpubNavigator needs a positions list to know where each reading-order
  // resource sits; prepare_book.py's own positions.json is written for real
  // reading apps' internal progression tracking (dense, text-length-based),
  // which this harness's direct-Locator-driven navigation doesn't need — one
  // synthetic position per resource is enough for go()'s href lookup. Actual
  // in-page navigation is driven entirely by the Locator passed to .go(),
  // via its href + cssSelector/text.highlight.
  const positions = manifest.readingOrder.items.map((link, i) =>
    Locator.deserialize({
      href: link.href,
      type: link.type,
      locations: { position: i + 1, progression: 0 },
    })
  );

  const navigator = new EpubNavigator(
    container,
    publication,
    {
      frameLoaded: () => {},
      positionChanged: (locator) => console.log("[positionChanged]", locator.href),
      timelineItemChanged: () => {},
      tap: () => false,
      click: () => false,
      zoom: () => {},
      miscPointer: () => {},
      scroll: () => {},
      customEvent: () => {},
      handleLocator: (locator) => {
        console.warn("[handleLocator] navigator could not resolve in-page, falling back:", locator);
        return false;
      },
      textSelected: () => {},
      contentProtection: () => {},
      contextMenu: () => {},
      peripheral: () => {},
    },
    positions,
    undefined,
    { preferences: {}, defaults: {} }
  );

  await navigator.load();
  return navigator;
}

// --- 2. Fetch BookSpine's Locators for a bookId and render them as a clickable list ---

let paragraphs = [];
let activeIndex = -1;
let navigatorInstance = null;
let navigating = false;

async function loadParagraphs(bookId) {
  setStatus(`Loading paragraphs for ${bookId}...`);
  const resp = await fetch(`${BOOKSPINE_API}/v1/publications/${encodeURIComponent(bookId)}/paragraphs`);
  if (!resp.ok) {
    throw new Error(`GET /v1/publications/${bookId}/paragraphs -> ${resp.status}`);
  }
  const body = await resp.json();
  paragraphs = body.paragraphs || [];
  renderParagraphList();
  setStatus(`Loaded ${paragraphs.length} paragraph Locators.`, "ok");
}

function renderParagraphList() {
  paragraphsEl.innerHTML = "";
  paragraphs.forEach((p, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<div class="meta">${p.paragraphId} &middot; ${p.href}</div><div class="text"></div>`;
    li.querySelector(".text").textContent = p.text;
    li.addEventListener("click", () => goToParagraph(i));
    paragraphsEl.appendChild(li);
  });
  updateActiveHighlight();
  updateNavButtons();
}

function updateActiveHighlight() {
  [...paragraphsEl.children].forEach((li, i) => li.classList.toggle("active", i === activeIndex));
}

function updateNavButtons() {
  prevBtn.disabled = activeIndex <= 0;
  nextBtn.disabled = activeIndex < 0 || activeIndex >= paragraphs.length - 1;
}

async function goToParagraph(index) {
  const p = paragraphs[index];
  if (!p || !navigatorInstance) return;

  // EpubNavigator.go() immediately calls back with `false` if a previous
  // .go() is still resolving (its own internal `_isNavigating` guard) —
  // unrelated to handleLocator/cssSelector resolution. Without this guard,
  // a fast double-click (or Prev/Next spammed) fires two overlapping .go()
  // calls: the second bounces off that guard and reports a bogus failure,
  // while the first's callback lands moments later reporting real success —
  // a confusing red-then-green flicker for what was actually one navigation.
  if (navigating) return;

  locatorJsonEl.textContent = JSON.stringify(p.locator, null, 2);

  const locator = Locator.deserialize(p.locator);
  if (!locator) {
    setStatus(`Locator.deserialize() failed for ${p.paragraphId}`, "error");
    return;
  }

  navigating = true;
  setStatus(`Navigating to ${p.paragraphId}...`);
  navigatorInstance.go(locator, true, (ok) => {
    navigating = false;
    activeIndex = index;
    updateActiveHighlight();
    updateNavButtons();
    setStatus(ok ? `Resolved ${p.paragraphId} in-page.` : `${p.paragraphId}: href not found in the publication's readingOrder (see console for the handleLocator warning).`, ok ? "ok" : "error");
  });
}

// --- 3. Populate the book picker from BookSpine, and figure out which book
// is actually the one being rendered. An explicit ?book= param says so
// directly; the default /book/manifest.json path doesn't carry a bookId in
// its URL, so that case is resolved by matching identifiers instead.

async function resolveCurrentBookId(manifestPath, books) {
  const fromUrl = new URLSearchParams(location.search).get("book");
  if (fromUrl) return fromUrl;

  try {
    const manifestJson = await fetch(manifestPath).then((r) => r.json());
    const match = books.find((b) => b.identifier === manifestJson.metadata?.identifier);
    if (match) return match.bookId;
  } catch {
    // fall through to the books[0] default below
  }
  return books[0]?.bookId || null;
}

async function populateBookSelect(manifestPath) {
  const resp = await fetch(`${BOOKSPINE_API}/v1/publications`);
  if (!resp.ok) throw new Error(`GET /v1/publications -> ${resp.status}`);
  const books = (await resp.json()).publications || [];

  bookSelectEl.innerHTML = "";
  books.forEach((b) => bookSelectEl.appendChild(new Option(b.title, b.bookId)));
  bookSelectEl.disabled = books.length === 0;

  const currentBookId = await resolveCurrentBookId(manifestPath, books);
  if (currentBookId) bookSelectEl.value = currentBookId;
  return currentBookId;
}

// --- wiring ---

const initialBookId = new URLSearchParams(location.search).get("book");
const initialManifestPath = manifestPathForBook(initialBookId);

loadBtn.addEventListener("click", () => {
  const bookId = bookSelectEl.value;
  if (!bookId) return setStatus("No book selected.", "error");
  loadParagraphs(bookId).catch((err) => setStatus(String(err), "error"));
});

// Picking a book navigates to its own manifest URL (a real reload) rather
// than swapping state in place — the EPUB actually rendered and the bookId
// paragraphs/search query against must never be able to drift apart.
bookSelectEl.addEventListener("change", () => {
  if (bookSelectEl.value) location.href = `?book=${encodeURIComponent(bookSelectEl.value)}`;
});

prevBtn.addEventListener("click", () => activeIndex > 0 && goToParagraph(activeIndex - 1));
nextBtn.addEventListener("click", () => activeIndex < paragraphs.length - 1 && goToParagraph(activeIndex + 1));

window.__harness = { get navigatorInstance() { return navigatorInstance; }, get paragraphs() { return paragraphs; }, goToParagraph };

populateBookSelect(initialManifestPath).catch((err) => setStatus(String(err), "error"));

loadPublication(initialManifestPath)
  .then((nav) => {
    navigatorInstance = nav;
    setStatus("EPUB loaded. Click Load paragraphs from BookSpine.", "ok");
  })
  .catch((err) => setStatus(`Failed to load EPUB: ${err}`, "error"));
