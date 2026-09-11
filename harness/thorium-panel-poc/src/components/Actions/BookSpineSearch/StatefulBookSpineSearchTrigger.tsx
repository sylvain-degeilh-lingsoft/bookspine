"use client";

import { ThActionsKeys } from "@/preferences/models";

import SearchIcon from "@/core/Components/Form/Fields/assets/icons/search.svg";

import { StatefulActionTriggerProps } from "../models/actions";
import { ThActionsTriggerVariant } from "@/core/Components/Actions/ThActionsBar";

import { StatefulActionIcon } from "../Triggers/StatefulActionIcon";
import { StatefulOverflowMenuItem } from "../Triggers/StatefulOverflowMenuItem";

import { useActionsPreferences } from "@/preferences/hooks/useActionsPreferences";

import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { setActionOpen } from "@/lib/actionsReducer";

// Proof of concept: same Trigger/Target action shape as StatefulTocTrigger,
// registered through its own plugin (createBookSpineSearchPlugin) rather than
// editing the core plugin, so it's purely additive.
const LABEL = "Search this book (BookSpine)";

export const StatefulBookSpineSearchTrigger = ({ variant }: StatefulActionTriggerProps) => {
  const preferences = useActionsPreferences();
  const profile = useAppSelector(state => state.reader.profile);
  const actionState = useAppSelector(state => profile ? state.actions.keys[profile][ThActionsKeys.bookspineSearch] : undefined);
  const dispatch = useAppDispatch();

  const setOpen = (value: boolean) => {
    if (profile) {
      dispatch(setActionOpen({
        key: ThActionsKeys.bookspineSearch,
        isOpen: value,
        profile
      }));
    }
  };

  return (
    <>
    { (variant && variant === ThActionsTriggerVariant.menu)
      ? <StatefulOverflowMenuItem
          label={ LABEL }
          SVGIcon={ SearchIcon }
          shortcut={ preferences.actionsKeys[ThActionsKeys.bookspineSearch]?.shortcut }
          id={ ThActionsKeys.bookspineSearch }
          onAction={ () => setOpen(!actionState?.isOpen) }
        />
      : <StatefulActionIcon
          visibility={ preferences.actionsKeys[ThActionsKeys.bookspineSearch]?.visibility }
          aria-label={ LABEL }
          placement="bottom"
          tooltipLabel={ LABEL }
          shortcut={ preferences.actionsKeys[ThActionsKeys.bookspineSearch]?.shortcut }
          onPress={ () => setOpen(!actionState?.isOpen) }
        >
          <SearchIcon aria-hidden="true" focusable="false" />
        </StatefulActionIcon>
    }
    </>
  );
};
