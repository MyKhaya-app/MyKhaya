"use client";

import { useState } from "react";
import Link from "next/link";
import type { SignupStateValue } from "@/components/public-signup";
import { SignupLink, signupIsSignIn } from "./signup-link";
import { SiteBrand } from "./site-brand";

export const SECTION_LINKS = [
  { id: "features", label: "Features" },
  { id: "day", label: "A day with us" },
  { id: "how", label: "How it works" },
  { id: "pricing", label: "Pricing" },
  { id: "faq", label: "FAQ" },
] as const;

/** Homepage section links are in-page anchors; on every other public page
 *  they point back to the homepage section. */
export function sectionHref(id: string, onHome: boolean) {
  return onHome ? `#${id}` : `/#${id}`;
}

export function SiteNav({ signupState, onHome }: { signupState: SignupStateValue; onHome: boolean }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const showSignIn = !signupIsSignIn(signupState);

  return (
    <header className="nav">
      <div className="wrap">
        <SiteBrand label="MyKhaya home" />
        <nav className="nav-links" aria-label="Main">
          {SECTION_LINKS.map(({ id, label }) => (
            <a key={id} href={sectionHref(id, onHome)}>
              {label}
            </a>
          ))}
        </nav>
        <div className="nav-cta">
          {showSignIn && (
            <Link className="signin" href="/login">
              Sign in
            </Link>
          )}
          <SignupLink className="btn btn-primary" state={signupState} />
          <button
            type="button"
            className="menu-btn"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "✕" : "☰"}
          </button>
        </div>
      </div>
      <div className="wrap mobile-menu" id="mobile-menu" hidden={!open}>
        {SECTION_LINKS.map(({ id, label }) => (
          <a key={id} href={sectionHref(id, onHome)} onClick={close}>
            {label}
          </a>
        ))}
        {showSignIn && (
          <Link href="/login" onClick={close}>
            Sign in
          </Link>
        )}
        <SignupLink state={signupState} suffix=" →" onClick={close} />
      </div>
    </header>
  );
}
