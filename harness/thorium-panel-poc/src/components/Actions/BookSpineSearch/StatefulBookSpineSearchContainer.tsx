"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Locator } from "@readium/shared";
import { DecorationStyleType } from "@readium/navigator";

import { ThActionsKeys } from "@/preferences/models";
import { StatefulActionContainerProps } from "../models/actions";

import bookspineSearchStyles from "./assets/styles/thorium-web.bookspineSearch.module.css";

import { StatefulSheetWrapper } from "../../Sheets/StatefulSheetWrapper";
import { ThForm } from "@/core/Components/Form/ThForm";
import { ThFormSearchField } from "@/core/Components/Form/Fields/ThFormSearchField";
import { StatefulDropdown } from "../../Settings/StatefulDropdown";
import { Button, type Key } from "react-aria-components";

import { useEpubNavigator } from "@/core/Hooks/Epub/useEpubNavigator";
import { useDocking } from "../../Docking/hooks/useDocking";

import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { setActionOpen } from "@/lib/actionsReducer";
import { setImmersive, setUserNavigated } from "@/lib/readerReducer";

// Proof of concept: a very basic keyword search over BookSpine's paragraph
// index, presented with the same Trigger/Target + StatefulSheetWrapper +
// useDocking machinery as the TOC panel — modal (popover/fullscreen
// depending on breakpoint) or docked to either side, per the same
// ThActionsTokens shape as any other first-party action. Results jump via
// useEpubNavigator().go(), the identical call TOC/JumpToPosition use.

const BOOKSPINE_API = process.env.NEXT_PUBLIC_BOOKSPINE_API || "http://localhost:8080";
// Where the harness's Vite dev server serves prepare_book.py's per-book output
// (public/books/{bookId}/manifest.json) — a different origin from BOOKSPINE_API,
// which is BookSpine's own API server.
const HARNESS_ORIGIN = process.env.NEXT_PUBLIC_BOOKSPINE_HARNESS_ORIGIN || "http://localhost:5173";
const DEFAULT_BOOK_ID = process.env.NEXT_PUBLIC_BOOKSPINE_BOOK_ID || "b_9781449328030";
const HIGHLIGHT_GROUP = "bookspine-search-hit";

interface SearchResult {
  paragraphId: string;
  href: string;
  text: string;
  locator: Record<string, unknown>;
}

interface PublicationSummary {
  bookId: string;
  title: string;
}

// The panel has no other way to know which book the page actually loaded —
// EpubNavigator/Redux don't surface it, and a page's Publication is set once
// from the manifest URL the route was opened with. Since every manifest URL
// this panel itself constructs (see handleBookChange) embeds the bookId as
// .../books/{bookId}/manifest.json, that URL is the actual source of truth:
// recover it instead of defaulting blind and silently searching the wrong
// book, as an env-var-only default did.
const currentBookIdFromLocation = (): string | null => {
  if (typeof window === "undefined") return null;
  const match = decodeURIComponent(window.location.pathname).match(/\/books\/([^/]+)\/manifest\.json$/);
  return match ? match[1] : null;
};

export const StatefulBookSpineSearchContainer = ({ triggerRef }: StatefulActionContainerProps) => {
  const { go, applyDecorations } = useEpubNavigator();

  const profile = useAppSelector(state => state.reader.profile);
  const actionState = useAppSelector(state => profile ? state.actions.keys[profile][ThActionsKeys.bookspineSearch] : undefined);
  const dispatch = useAppDispatch();

  const docking = useDocking(ThActionsKeys.bookspineSearch);
  const sheetType = docking.sheetType;

  const [bookId, setBookId] = useState(() => currentBookIdFromLocation() ?? DEFAULT_BOOK_ID);
  const [books, setBooks] = useState<PublicationSummary[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [status, setStatus] = useState("");
  const [statusIsError, setStatusIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const navigating = useRef(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${ BOOKSPINE_API }/v1/publications`)
      .then((resp) => resp.ok ? resp.json() : Promise.reject(new Error(`GET /publications -> ${ resp.status }`)))
      .then((body) => {
        if (cancelled) return;
        const list: PublicationSummary[] = body.publications || [];
        setBooks(list);
        // Keep the URL-derived (or env-default) guess if it's actually in the
        // list; otherwise fall back to whatever BookSpine has, rather than a
        // bookId that 404s.
        if (list.length > 0 && !list.some((b) => b.bookId === bookId)) {
          setBookId(list[0].bookId);
        }
      })
      .catch((err) => {
        if (!cancelled) setStatus(String(err));
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setOpen = useCallback((value: boolean) => {
    if (profile) {
      dispatch(setActionOpen({ key: ThActionsKeys.bookspineSearch, isOpen: value, profile }));
    }
  }, [dispatch, profile]);

  // A page's Publication is bound to whatever manifest it was opened with —
  // nothing this panel does in place can swap what EpubNavigator is actually
  // rendering. So picking a different book means navigating to that book's
  // own manifest URL (a full page load), not just changing which bookId
  // subsequent /search calls target.
  const handleBookChange = useCallback((key: Key) => {
    const newBookId = String(key);
    if (newBookId === bookId) return;
    const manifestUrl = `${ HARNESS_ORIGIN }/books/${ encodeURIComponent(newBookId) }/manifest.json`;
    window.location.href = `/read/manifest/${ encodeURIComponent(manifestUrl) }`;
  }, [bookId]);

  const handleSearch = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !bookId.trim()) return;

    setLoading(true);
    setStatus("");
    setStatusIsError(false);

    try {
      const url = `${ BOOKSPINE_API }/v1/publications/${ encodeURIComponent(bookId) }/search?q=${ encodeURIComponent(query) }&limit=5`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`GET /search -> ${ resp.status }`);
      const body = await resp.json();
      setResults(body.results || []);
      setStatus(`${ (body.results || []).length } result(s) for "${ query }".`);
    } catch (err) {
      setResults([]);
      setStatus(String(err));
      setStatusIsError(true);
    } finally {
      setLoading(false);
    }
  }, [query, bookId]);

  const handleJump = useCallback((result: SearchResult) => {
    // EpubNavigator.go() calls back with false immediately if a previous
    // .go() is still resolving — ignore overlapping jumps.
    if (navigating.current) return;

    const locator = Locator.deserialize(result.locator);
    if (!locator) {
      setStatus(`Locator.deserialize() failed for ${ result.paragraphId }`);
      setStatusIsError(true);
      return;
    }

    navigating.current = true;
    setStatus(`Jumping to ${ result.paragraphId }...`);
    setStatusIsError(false);

    const isDocked = sheetType === "docked start" || sheetType === "docked end";
    const cb = (ok: boolean) => {
      navigating.current = false;
      setActiveId(result.paragraphId);
      setStatus(ok ? `Resolved ${ result.paragraphId } in-page.` : `${ result.paragraphId }: href not found in the publication's readingOrder.`);
      setStatusIsError(!ok);
      dispatch(setImmersive(true));
      dispatch(setUserNavigated(true));
      if (!isDocked) setOpen(false);

      // Replaces the whole group each call, so exactly one hit is
      // highlighted at a time — the one just jumped to.
      applyDecorations(
        ok ? [{ id: result.paragraphId, locator, style: { type: DecorationStyleType.Highlight } }] : [],
        HIGHLIGHT_GROUP
      );
    };

    go(locator, true, cb);
  }, [go, applyDecorations, sheetType, dispatch, setOpen]);

  return (
    <StatefulSheetWrapper
      sheetType={ sheetType }
      sheetProps={ {
        id: ThActionsKeys.bookspineSearch,
        triggerRef: triggerRef,
        heading: "Search this book (BookSpine)",
        className: bookspineSearchStyles.wrapper,
        placement: "bottom",
        isOpen: actionState?.isOpen || false,
        onOpenChange: setOpen,
        onClosePress: () => setOpen(false),
        docker: docking.getDocker()
      } }
    >
      <ThForm
        label="Search"
        className={ bookspineSearchStyles.form }
        onSubmit={ handleSearch }
        compounds={ { button: { isDisabled: loading || !query.trim() || !bookId.trim() } } }
      >
        <StatefulDropdown
          label="Book"
          className={ bookspineSearchStyles.bookIdDropdown }
          items={ books.map((b) => ({ id: b.bookId, label: b.title, value: b.bookId })) }
          selectedKey={ bookId }
          onSelectionChange={ handleBookChange }
          isDisabled={ books.length === 0 }
        />

        <ThFormSearchField
          aria-label="Search this book"
          value={ query }
          onChange={ setQuery }
          onClear={ () => setQuery("") }
          className={ bookspineSearchStyles.search }
          compounds={ {
            input: {
              className: bookspineSearchStyles.searchInput,
              placeholder: "Search this book…"
            },
            searchIcon: { className: bookspineSearchStyles.searchIcon, hidden: !!query },
            clearButton: {
              className: bookspineSearchStyles.clearButton,
              isDisabled: !query,
              "aria-label": "Clear"
            }
          } }
        />
      </ThForm>

      { status && (
        <div className={ bookspineSearchStyles.status } data-error={ statusIsError || undefined }>
          { status }
        </div>
      ) }

      { results.length > 0 && (
        <ul className={ bookspineSearchStyles.results }>
          { results.map((r) => (
            <li
              key={ r.paragraphId }
              className={ bookspineSearchStyles.result }
              data-active={ activeId === r.paragraphId || undefined }
            >
              <div className={ bookspineSearchStyles.resultBody }>
                <div className={ bookspineSearchStyles.resultHref }>{ r.href }</div>
                <div className={ bookspineSearchStyles.resultText }>{ r.text }</div>
              </div>
              <Button className={ bookspineSearchStyles.jumpButton } onPress={ () => handleJump(r) }>
                Jump
              </Button>
            </li>
          )) }
        </ul>
      ) }
    </StatefulSheetWrapper>
  );
};
