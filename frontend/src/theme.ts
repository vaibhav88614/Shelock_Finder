// Light/dark theme controller. Reads a saved preference from localStorage on
// boot (falling back to the OS setting) and applies the `.dark` class to
// <html> so Tailwind's `dark:` variants take effect.

export type Theme = "light" | "dark";

const STORAGE_KEY = "jobpulse_theme";

export function getSavedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return null;
}

export function getSystemTheme(): Theme {
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "light";
}

export function getEffectiveTheme(): Theme {
  return getSavedTheme() ?? getSystemTheme();
}

export function applyTheme(t: Theme): void {
  const root = document.documentElement;
  if (t === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
}

export function saveTheme(t: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, t);
  } catch {
    /* ignore */
  }
}

/** Boot-time helper — run once from `main.tsx` before React mounts. */
export function initTheme(): void {
  applyTheme(getEffectiveTheme());
}
