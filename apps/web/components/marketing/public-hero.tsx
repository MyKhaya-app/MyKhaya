import Link from "next/link";
import { Logo } from "@/components/logo";

const REASSURANCE_POINTS = [
  "Free to start",
  "No card required",
  "Set up in minutes",
] as const;

export function PublicHero() {
  return (
    <section className="mk-hero">
      <div className="mk-hero-copy">
        <p className="eyebrow">A happier, more organised home</p>
        <h1>Bring your family together.</h1>
        <p className="mk-hero-lead">
          Shared calendars, meals, lists and nudges — all in one place. Less
          stress, more time for what really matters.
        </p>
        <div className="mk-hero-actions">
          <Link className="button large" href="/register">
            Get started free
          </Link>
          <Link className="button secondary large" href="/login">
            Sign in
          </Link>
        </div>
        <ul className="mk-hero-reassurance">
          {REASSURANCE_POINTS.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      </div>
      <div className="mk-hero-art" aria-hidden="true">
        <div className="mk-hero-phone one">
          <Logo compact />
        </div>
        <div className="mk-hero-phone two">
          <span className="mk-art-card">
            Family dinner
            <br />
            <small>Tonight · 18:00</small>
          </span>
          <span className="mk-art-card">
            ✓ Take the bins out
            <br />
            <small>Today · Routine</small>
          </span>
        </div>
        <div className="mk-hero-phone three">
          <span className="mk-art-card">
            School pickup
            <br />
            <small>15:00</small>
          </span>
        </div>
      </div>
    </section>
  );
}
