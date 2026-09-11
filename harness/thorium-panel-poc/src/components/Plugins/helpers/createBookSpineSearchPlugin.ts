import { ThPlugin } from "../PluginRegistry";
import { ThActionsKeys } from "@/preferences/models";

import { StatefulBookSpineSearchTrigger } from "../../Actions/BookSpineSearch/StatefulBookSpineSearchTrigger";
import { StatefulBookSpineSearchContainer } from "../../Actions/BookSpineSearch/StatefulBookSpineSearchContainer";

// Additive proof-of-concept plugin: registered alongside createDefaultPlugin()
// (see app/read/manifest/[manifest]/page.tsx) rather than merged into it, so
// none of the first-party action wiring needs to change to add this one.
export const createBookSpineSearchPlugin = (): ThPlugin => {
  return {
    id: "bookspine-search",
    name: "BookSpine Search",
    description: "Keyword search over a BookSpine-indexed publication, jumping to results via the real navigator.",
    version: "0.1.0",
    components: {
      actions: {
        [ThActionsKeys.bookspineSearch]: {
          Trigger: StatefulBookSpineSearchTrigger,
          Target: StatefulBookSpineSearchContainer
        }
      }
    }
  };
};
