"use client";

import { FormEvent, useCallback, useRef, useState } from "react";
import { Locator } from "@readium/shared";
import { DecorationStyleType } from "@readium/navigator";

import { ThActionsKeys } from "@/preferences/models";
import { StatefulActionContainerProps } from "../models/actions";

import bookspineSearchStyles from "./assets/styles/thorium-web.bookspineSearch.module.css";

import { StatefulSheetWrapper } from "../../Sheets/StatefulSheetWrapper";
import { ThForm } from "@/core/Components/Form/ThForm";
import { ThFormSearchField } from "@/core/Components/Form/Fields/ThFormSearchField";
import { Button } from "react-aria-components";

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
const DEFAULT_BOOK_ID = process.env.NEXT_PUBLIC_BOOKSPINE_BOOK_ID || "b_9781449328030";
const HIGHLIGHT_GROUP = "bookspine-search-hit";

interface SearchResult {
  paragraphId: string;
  href: string;
  text: string;
  locator: Record<string, unknown>;
}

export const StatefulBookSpineSearchContainer = ({ triggerRef }: StatefulActionContainerProps) => {
  const { go, applyDecorations } = useEpubNavigator();

  const profile = useAppSelector(state => state.reader.profile);
  const actionState = useAppSelector(state => profile ? state.actions.keys[profile][ThActionsKeys.bookspineSearch] : undefined);
  const dispatch = useAppDispatch();

  const docking = useDocking(ThActionsKeys.bookspineSearch);
  const sheetType = docking.sheetType;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [status, setStatus] = useState("");
  const [statusIsError, setStatusIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const navigating = useRef(false);

  const setOpen = useCallback((value: boolean) => {
    if (profile) {
      dispatch(setActionOpen({ key: ThActionsKeys.bookspineSearch, isOpen: value, profile }));
    }
  }, [dispatch, profile]);

  const handleSearch = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setStatus("");
    setStatusIsError(false);

    try {
      const url = `${ BOOKSPINE_API }/v1/publications/${ encodeURIComponent(DEFAULT_BOOK_ID) }/search?q=${ encodeURIComponent(query) }&limit=5`;
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
  }, [query]);

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
        compounds={ { button: { isDisabled: loading || !query.trim() } } }
      >
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
