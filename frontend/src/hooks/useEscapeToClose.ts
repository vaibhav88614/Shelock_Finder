import { useEffect } from "react";

/**
 * Closes the consumer when the user presses Escape anywhere on the page.
 * Used by modals and drawers to satisfy WCAG 2.1.2 keyboard escape.
 *
 * The `onClose` reference is read every keydown; consumers don't need to
 * memoize it (no false re-mounts).
 */
export function useEscapeToClose(onClose: () => void): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
}
