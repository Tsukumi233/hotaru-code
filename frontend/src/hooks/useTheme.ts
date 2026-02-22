import { useCallback, useEffect, useState } from "react";
import type { Theme } from "../types";

function resolved(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("hotaru-theme") as Theme) || "system");

  const apply = useCallback((t: Theme) => {
    setTheme(t);
    localStorage.setItem("hotaru-theme", t);
    if (t === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", t);
    }
  }, []);

  useEffect(() => {
    if (theme !== "system") {
      document.documentElement.setAttribute("data-theme", theme);
      return;
    }
    document.documentElement.removeAttribute("data-theme");
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setTheme("system");
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [theme]);

  return { theme, resolved: resolved(theme), setTheme: apply };
}
