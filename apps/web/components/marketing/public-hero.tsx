import Link from "next/link";
import { Logo } from "@/components/logo";

export function PublicHero() {
  return (
    <section className="mk-hero">
      <div className="mk-hero-copy">
        <h1>
          Your family. One place.
          <br />
          Everything organised.
        </h1>
        <p className="mk-hero-lead">
          Calendars, routines, lists, chores and the everyday things that keep
          your home running.
        </p>
        <div className="mk-hero-actions">
          <Link className="button large" href="/register">
            Get started free
          </Link>
          <Link className="button secondary large" href="/login">
            Sign in
          </Link>
        </div>
      </div>
      <div className="mk-hero-art" aria-hidden="true">
        <Logo compact />
        <span className="mk-art-card one">
          Family lunch
          <br />
          <small>Sunday · 13:00</small>
        </span>
        <span className="mk-art-card two">
          ✓ Take the bins out
          <br />
          <small>Due today</small>
        </span>
        <span className="mk-art-card three">
          Recycling
          <br />
          <small>Out tonight</small>
        </span>
      </div>
    </section>
  );
}
