import { useCallback, useEffect, useRef, useState } from "react";

export function useAutoScroll(deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const userScrolled = useRef(false);

  const scrollToBottom = useCallback(() => {
    if (!ref.current) return;
    ref.current.scrollTop = ref.current.scrollHeight;
    setPinned(true);
    userScrolled.current = false;
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = () => {
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (gap < 40) {
        setPinned(true);
        userScrolled.current = false;
      } else {
        setPinned(false);
        userScrolled.current = true;
      }
    };
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, []);

  useEffect(() => {
    if (!userScrolled.current && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, deps);

  return { ref, pinned, scrollToBottom };
}
