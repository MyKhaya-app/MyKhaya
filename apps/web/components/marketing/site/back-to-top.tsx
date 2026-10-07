"use client";

import { useEffect, useState } from "react";

export function BackToTop() {
  const [away, setAway] = useState(true);
  useEffect(() => {
    const onScroll = () => setAway(window.scrollY < 600);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <button
      type="button"
      className={`to-top${away ? " away" : ""}`}
      aria-label="Back to top"
      tabIndex={away ? -1 : undefined}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
    >
      ↑
    </button>
  );
}
