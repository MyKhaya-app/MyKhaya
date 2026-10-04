"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2 } from "lucide-react";

const DEFAULT_DURATION_MS = 2500;

export function Toast({
  message,
  onDismiss,
  duration = DEFAULT_DURATION_MS,
}: {
  message: string;
  onDismiss: () => void;
  duration?: number;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(timer);
  }, [duration, message, onDismiss]);

  if (!mounted || !message) return null;

  return createPortal(
    <div className="consumer-toast-region" aria-live="polite" aria-atomic="true">
      <div className="consumer-toast" role="status">
        <CheckCircle2 size={18} aria-hidden="true" />
        <span>{message}</span>
      </div>
    </div>,
    document.body,
  );
}
