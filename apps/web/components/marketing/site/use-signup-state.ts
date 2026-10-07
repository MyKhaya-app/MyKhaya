"use client";

import { useEffect, useState } from "react";
import { api } from "@mykhaya/api-client";
import type { SignupStateValue } from "@/components/public-signup";

/** Loads the public signup mode (normal / beta_only / mixed / closed) once.
 *  `undefined` while loading, `null` if it could not be loaded — see
 *  SignupStateValue. Disabled when the page already holds it. */
export function useSignupState(enabled = true): SignupStateValue {
  const [state, setState] = useState<SignupStateValue>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .publicSignupState()
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        if (!cancelled) setState(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return state;
}
