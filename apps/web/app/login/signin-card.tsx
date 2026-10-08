import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { SignupStateValue } from "@/components/public-signup";

// The card under the sign-in form. Founding Beta and "New to MyKhaya?" share
// one structure; only colour (via the modifier class) and copy differ.

function HousePlusIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9" />
      <path d="M12 12v5" />
      <path d="M9.5 14.5h5" />
    </svg>
  );
}

function HouseStarIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9" />
      <path d="M12 11.5l.9 1.9 2.1.3-1.5 1.4.4 2.1-1.9-1-1.9 1 .4-2.1-1.5-1.4 2.1-.3z" />
    </svg>
  );
}

const variants = {
  beta: {
    titleId: "signin-beta-title",
    icon: <HouseStarIcon />,
    eyebrow: "Founding Beta",
    title: "Help shape a calmer home.",
    body: "Join a small group of households testing MyKhaya and help shape what’s next.",
    action: "Join the Founding Beta",
  },
  new: {
    titleId: "signin-new-title",
    icon: <HousePlusIcon />,
    eyebrow: "New to MyKhaya?",
    title: "Create your Home and get started.",
    body: "Organise your household, plan together and make everyday life a little calmer.",
    action: "Create an account",
  },
} as const;

export function SignInCard({ variant, href }: { variant: keyof typeof variants; href: string }) {
  const card = variants[variant];
  return (
    <section
      className={`signin-card signin-card--${variant}`}
      aria-labelledby={card.titleId}
      data-testid={`signin-card-${variant}`}
    >
      <div className="signin-card-row">
        <div className="signin-card-tile">{card.icon}</div>
        <div className="signin-card-text">
          <span className="signin-card-eyebrow">{card.eyebrow}</span>
          <h2 id={card.titleId}>{card.title}</h2>
          <p>{card.body}</p>
        </div>
      </div>
      <Link className="signin-card-action" href={href}>
        {card.action}
        <ArrowRight size={18} strokeWidth={2} aria-hidden="true" />
      </Link>
    </section>
  );
}

/** Which card sits under the sign-in form, from the live signup state
 *  (undefined while loading, null if it failed: both give the normal card).
 *  - Registration closed/paused, or invitation-only without a valid
 *    household invitation: the Founding Beta card if the waitlist is open
 *    (/founding-beta leads to it), otherwise no card.
 *  - Beta places open, or the waitlist is the only way in: Founding Beta.
 *  - Otherwise "New to MyKhaya?", carrying any household or calendar-share
 *    invitation into registration. */
export function signInCard(
  state: SignupStateValue,
  context: { invitation: string | null; calendarShare: string | null; invitationValid: boolean },
): "beta" | "new" | null {
  if (!state) return "new";
  const waitlistOpen = state.waitlist_available === true;
  const closed = state.registration_open === false;
  const inviteOnlyWithoutInvitation = state.invitation_required === true && !context.invitationValid;
  if (closed || inviteOnlyWithoutInvitation) return waitlistOpen ? "beta" : null;
  const betaIsTheWayIn =
    state.beta_joining_available === true || (waitlistOpen && state.normal_signup_available === false);
  return betaIsTheWayIn && !context.invitation && !context.calendarShare ? "beta" : "new";
}
