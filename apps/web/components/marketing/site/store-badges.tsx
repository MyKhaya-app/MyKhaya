"use client";

import { AppLinks } from "@/components/app-links/app-links";
import { useSignupStateContext } from "./signup-state-context";

/** App Store / Google Play badges under the homepage hero, driven by the PCC
 *  "iPhone app link" / "Android app link" settings (public signup-state).
 *  Only real store listings are linked; otherwise the official badges stay
 *  as artwork (Google Play with a "Coming soon" pill). Hidden in the native
 *  app. */
export function StoreBadges() {
  const signupState = useSignupStateContext();
  return <AppLinks ios={signupState?.ios_app_url} android={signupState?.android_app_url} surface="homepage" />;
}
