"use client";

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { LogOut, Settings, Shield, User as UserIcon } from "lucide-react";
import type { User } from "@mykhaya/shared-types";

/** First character kept, everything else in the local part collapsed to a
 *  fixed run of bullets (never reveals length) — e.g. "anthony@x.com" ->
 *  "a•••@x.com". Uses only the email already present on the in-memory User
 *  object; never triggers a request to obtain or verify it. */
export function maskEmail(email: string): string {
  const at = email.indexOf("@");
  if (at <= 0) return email;
  return `${email.slice(0, 1)}•••${email.slice(at)}`;
}

/**
 * Compact, anchored account dropdown for desktop/tablet browser widths —
 * the desktop counterpart to AppHeader's mobile/native BottomSheet menu.
 * Rendered via a portal to document.body so its fixed positioning escapes
 * .app-header's own `overflow: hidden` and stacking context; position is
 * computed from the anchor's own on-screen rect, not CSS anchoring, since
 * there is no popover-anchor support target in this codebase yet.
 */
export function AccountMenu({
  anchorRef,
  user,
  onClose,
  onSignOut,
  signingOut,
  signOutError,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  user: User | null;
  onClose: () => void;
  onSignOut: () => void;
  signingOut: boolean;
  signOutError: string | null;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null);

  useLayoutEffect(() => {
    function place() {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      setPosition({
        top: rect.bottom + 8,
        right: Math.max(window.innerWidth - rect.right, 12),
      });
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchorRef]);

  useEffect(() => {
    menuRef.current?.focus();
    function handlePointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    }
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeydown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeydown);
      // Sensible focus return: the trigger is exactly what the user's
      // attention was on before opening this menu.
      anchorRef.current?.focus();
    };
  }, [anchorRef, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={menuRef}
      className="account-menu"
      tabIndex={-1}
      aria-label="Account menu"
      style={position ? { top: position.top, right: position.right } : { visibility: "hidden" }}
    >
      <div className="account-menu-identity">
        <strong>{user?.display_name ?? "Your account"}</strong>
        {user?.email && <small className="muted">{maskEmail(user.email)}</small>}
      </div>
      <div className="account-menu-divider" role="separator" />
      <nav className="account-menu-items">
        <Link href="/settings/profile" className="account-menu-item" onClick={onClose}>
          <UserIcon size={18} aria-hidden="true" />
          Profile
        </Link>
        <Link href="/settings" className="account-menu-item" onClick={onClose}>
          <Settings size={18} aria-hidden="true" />
          Settings
        </Link>
        <Link href="/settings/security" className="account-menu-item" onClick={onClose}>
          <Shield size={18} aria-hidden="true" />
          Security
        </Link>
      </nav>
      <div className="account-menu-divider" role="separator" />
      <button
        type="button"
        className="account-menu-item danger"
        onClick={onSignOut}
        disabled={signingOut}
      >
        <LogOut size={18} aria-hidden="true" />
        {signingOut ? "Signing out…" : "Sign out"}
      </button>
      {signOutError && (
        <p className="account-menu-error" role="alert">
          {signOutError}
        </p>
      )}
    </div>,
    document.body,
  );
}
