"use client";

import "@/app/marketing-site.css";
import type { SignupStateValue } from "@/components/public-signup";
import { SiteFooter } from "./site-footer";
import { SiteNav } from "./site-nav";
import { useSignupState } from "./use-signup-state";

/** The marketing nav and footer around an existing public page (legal,
 *  Founding Beta, signup choice, support). Only the nav and footer sit inside
 *  the scoped `.mks` styles (as `display: contents` wrappers, so the sticky nav
 *  still sticks); the page's own content between them is left untouched and
 *  keeps the light app styling, so these wrappers are pinned to light. */
export function MarketingChrome({
  children,
  signupState,
  ownSignupState = false,
}: {
  children: React.ReactNode;
  /** The page's own signup state, when `ownSignupState` is set (the page
   *  already loads it); otherwise the chrome loads it itself. */
  signupState?: SignupStateValue;
  ownSignupState?: boolean;
}) {
  const fetched = useSignupState(!ownSignupState);
  const state = ownSignupState ? signupState : fetched;
  return (
    <div className="mks-page">
      <div className="mks mks-scope" data-theme="light">
        <SiteNav signupState={state} onHome={false} />
      </div>
      {children}
      <div className="mks mks-scope" data-theme="light">
        <SiteFooter onHome={false} />
      </div>
    </div>
  );
}
