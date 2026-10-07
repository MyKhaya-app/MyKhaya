"use client";

import { useState } from "react";
import Link from "next/link";
import type { SignupStateValue } from "@/components/public-signup";
import { SignupLink, signupIsSignIn } from "./signup-link";
import { useSignupStateContext } from "./signup-state-context";
import { SiteBrand } from "./site-brand";
import { SECTION_LINKS, sectionHref } from "./site-links";

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

/** The homepage nav, reading the signup mode from SignupStateProvider. */
export function HomeNav() {
  return <SiteNav signupState={useSignupStateContext()} onHome />;
}
