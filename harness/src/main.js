import { HttpFetcher, Locator, Manifest, Publication } from "@readium/shared";
import { EpubNavigator } from "@readium/navigator";

const statusEl = document.getElementById("status");
const paragraphsEl = document.getElementById("paragraphs");
const locatorJsonEl = document.getElementById("locator-json");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const loadBtn = document.getElementById("load-btn");
const bookIdInput = document.getElementById("book-id");
const container = document.getElementById("reader-container");

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = kind || "";
}

// --- 1. Load the EPUB (unpacked by prepare_book.py, served statically from /book/) ---

async function loadPublication() {
  const manifestJson = await fetch("/book/manifest.json").then((r) => {
    if (!r.ok) throw new Error(`GET /book/manifest.json -> ${r.status}`);
    return r.json();
  });

  // Manifest.baseURL is derived by stripping the filename off the `self`
  // link's href, so it must be absolute (a relative "manifest.json" strips
  // down to "" and every later Link.toURL(base) call throws "Invalid base
  // URL") — rewrite it to wherever this page actually fetched it from,
  // instead of baking a fixed origin/port into the static manifest file.
  const selfLink = manifestJson.links?.find((l) => l.rel === "self" || (Array.isArray(l.rel) && l.rel.includes("self")));
  if (selfLink) selfLink.href = new URL("/book/manifest.json", location.origin).href;

  const manifest = Manifest.deserialize(manifestJson);
  if (!manifest) throw new Error("Manifest.deserialize() returned undefined — check /book/manifest.json shape");

  const fetcher = new HttpFetcher(undefined, `${location.origin}/book/`);
  const publication = new Publication({ manifest, fetcher });

  // EpubNavigator needs a positions list to know where each reading-order
  // resource sits; we don't have a real position-list.json, so synthesize
  // one position per resource. `go()` only uses this to update its own
  // book-progress bookkeeping — actual in-page navigation is driven entirely
  // by the Locator passed to .go(), via its href + cssSelector/text.highlight.
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
  const resp = await fetch(`/api/v1/publications/${encodeURIComponent(bookId)}/paragraphs`);
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

// --- wiring ---

loadBtn.addEventListener("click", () => {
  const bookId = bookIdInput.value.trim();
  if (!bookId) return setStatus("Enter a bookId first.", "error");
  loadParagraphs(bookId).catch((err) => setStatus(String(err), "error"));
});

prevBtn.addEventListener("click", () => activeIndex > 0 && goToParagraph(activeIndex - 1));
nextBtn.addEventListener("click", () => activeIndex < paragraphs.length - 1 && goToParagraph(activeIndex + 1));

window.__harness = { get navigatorInstance() { return navigatorInstance; }, get paragraphs() { return paragraphs; }, goToParagraph };

loadPublication()
  .then((nav) => {
    navigatorInstance = nav;
    setStatus("EPUB loaded. Enter a bookId and load its paragraphs.", "ok");
  })
  .catch((err) => setStatus(`Failed to load EPUB: ${err}`, "error"));
