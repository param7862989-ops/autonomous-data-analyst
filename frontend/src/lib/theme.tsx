"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

/**
 * Colour theme. "system" follows the operating system; "light" and "dark" are stamped on
 * <html data-theme> and win over it. The choice is a per-browser convenience kept in
 * localStorage (public/theme-init.js applies it before the first paint).
 */
export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "ada-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

type ThemeContextValue = {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  preference: "system",
  resolved: "light",
  setPreference: () => {},
});

// --- Preference store (localStorage, with an in-memory fallback when storage is blocked) ---

const listeners = new Set<() => void>();
let memoryPreference: ThemePreference = "system";

function parse(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

function readPreference(): ThemePreference {
  try {
    return parse(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return memoryPreference;
  }
}

function subscribePreference(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab changed the theme.
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function writePreference(next: ThemePreference): void {
  memoryPreference = next;
  const root = document.documentElement;
  if (next === "system") delete root.dataset.theme;
  else root.dataset.theme = next;
  try {
    if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // Not persisted; the in-memory value still applies to this page.
  }
  listeners.forEach((listener) => listener());
}

// --- Operating-system setting --------------------------------------------------------------

function subscribeSystem(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(DARK_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function readSystem(): ResolvedTheme {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches
    ? "dark"
    : "light";
}

// The server cannot know either value; it renders the defaults and the client syncs on hydrate.
const serverPreference = (): ThemePreference => "system";
const serverSystem = (): ResolvedTheme => "light";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const preference = useSyncExternalStore(subscribePreference, readPreference, serverPreference);
  const system = useSyncExternalStore(subscribeSystem, readSystem, serverSystem);
  const setPreference = useCallback((next: ThemePreference) => writePreference(next), []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolved: preference === "system" ? system : preference,
      setPreference,
    }),
    [preference, system, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
