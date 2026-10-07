"use client";

import { createContext, useContext } from "react";
import type { SignupStateValue } from "@/components/public-signup";
import { useSignupState } from "./use-signup-state";

const SignupStateContext = createContext<SignupStateValue>(undefined);

/** Loads the public signup mode once for the homepage and shares it with the
 *  few client islands that depend on it (nav, hero actions, pricing, final
 *  CTA), so the rest of the page can stay server-rendered. */
export function SignupStateProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const state = useSignupState(enabled);
  return <SignupStateContext.Provider value={state}>{children}</SignupStateContext.Provider>;
}

export function useSignupStateContext(): SignupStateValue {
  return useContext(SignupStateContext);
}
