import Link from "next/link";
import { signupCtaLabel, signupDestination, type SignupStateValue } from "@/components/public-signup";

/** The main sign-up action, following the signup mode ("Get started free",
 *  "Join the Beta", "Choose how to join", "Join the waitlist"…). Until the mode
 *  is known it holds its space invisibly instead of showing a label that may
 *  be about to change. */
export function SignupLink({
  state,
  className,
  suffix = "",
  onClick,
}: {
  state: SignupStateValue;
  className?: string;
  suffix?: string;
  onClick?: () => void;
}) {
  const pending = state === undefined;
  return (
    <Link
      className={className}
      href={signupDestination(state ?? null)}
      onClick={onClick}
      style={pending ? { visibility: "hidden" } : undefined}
      aria-hidden={pending || undefined}
      tabIndex={pending ? -1 : undefined}
    >
      {signupCtaLabel(state ?? null)}
      {suffix}
    </Link>
  );
}

/** True when the sign-up action would itself be "Sign in" (sign-ups closed, no
 *  waitlist), so a separate Sign in link next to it would be a duplicate. */
export function signupIsSignIn(state: SignupStateValue): boolean {
  return signupDestination(state ?? null) === "/login";
}
