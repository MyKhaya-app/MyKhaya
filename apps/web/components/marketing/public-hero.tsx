import Link from "next/link";

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
        <div className="mk-hero-phone meal">
          <img
            src="/images/marketing/mykhaya-meal-plans.png"
            alt="The MyKhaya Meal Plans screen, showing today's breakfast, lunch and dinner"
            loading="eager"
          />
        </div>
        <div className="mk-hero-phone home">
          <img
            src="/images/marketing/mykhaya-home.png"
            alt="The MyKhaya Home screen, showing today's to-dos and household members"
            loading="eager"
          />
        </div>
        <div className="mk-hero-phone calendar">
          <img
            src="/images/marketing/mykhaya-calendar.png"
            alt="The MyKhaya Calendar screen, showing a month of shared family events"
            loading="eager"
          />
        </div>
      </div>
    </section>
  );
}
