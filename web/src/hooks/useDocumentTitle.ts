/**
 * Sets the document title for the current view.
 *
 * A single-page application keeps whatever title the HTML shipped with unless
 * something changes it, so every route would otherwise read "Academious" in the
 * tab, in the history and in a bookmark. A reader with four papers open in four
 * tabs needs those tabs to be different from each other.
 *
 * Pass `null` while a record is still loading: the shell title stays until
 * there is something true to say.
 */

import { useEffect } from "react";

const SITE = "Academious";

export function useDocumentTitle(title: string | null) {
  useEffect(() => {
    if (title === null) return;
    const previous = document.title;
    document.title = title === SITE ? SITE : `${title} · ${SITE}`;
    // Restoring on unmount keeps a back-navigation from inheriting the title of
    // the page it left.
    return () => {
      document.title = previous;
    };
  }, [title]);
}
