"use client";
import { useCallback, useEffect, useState } from "react";
export type Theme = "light" | "dark";
export type Density = "comfortable" | "compact";
const KEY = "my-pa:shell-preferences:v1";
type Preferences = {
  theme: Theme;
  density: Density;
  navCollapsed: boolean;
  utilityPinned: boolean;
  utilityWidth: number;
};
const DEFAULTS: Preferences = {
  theme: "light",
  density: "comfortable",
  navCollapsed: false,
  utilityPinned: false,
  utilityWidth: 360,
};

export function useShellPreferences() {
  const [preferences, setPreferences] = useState(DEFAULTS);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const initialHydration = window.setTimeout(() => {
      try {
        const stored = localStorage.getItem(KEY);
        if (stored) setPreferences({ ...DEFAULTS, ...JSON.parse(stored) });
      } catch {}
      setHydrated(true);
    }, 0);
    return () => window.clearTimeout(initialHydration);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document.documentElement.dataset.density = preferences.density;
    if (!hydrated) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(preferences));
    } catch {}
  }, [hydrated, preferences]);

  const update = useCallback(
    (patch: Partial<Preferences>) =>
      setPreferences((current) => ({ ...current, ...patch })),
    [],
  );
  return { preferences, update };
}
