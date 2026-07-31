import Link from "next/link";
import { Logo } from "@/components/logo";
export default function Welcome() {
  return (
    <main className="welcome">
      <nav>
        <Logo />
        <div>
          <Link className="button secondary" href="/login">
            Sign in
          </Link>
          <Link className="button" href="/register">
            Create account
          </Link>
        </div>
      </nav>
      <section>
        <div>
          <p className="eyebrow">Private coordination for real life</p>
          <h1>
            Your family’s
            <br />
            <em>digital home.</em>
          </h1>
          <p className="lead">
            Plans, people, shopping and the small things that keep life
            moving—calmly together in one private place.
          </p>
          <div className="welcome-actions">
            <Link className="button large" href="/register">
              Start your Home
            </Link>
            <Link className="text-link" href="/login">
              I already have an account →
            </Link>
          </div>
        </div>
        <div className="welcome-art" aria-hidden="true">
          <Logo compact />
          <span className="art-card one">
            Family lunch
            <br />
            <small>Sunday · 13:00</small>
          </span>
          <span className="art-card two">
            ✓ Take the bins out
            <br />
            <small>Due today</small>
          </span>
          <span className="art-card three">
            Shopping
            <br />
            <small>4 things added</small>
          </span>
        </div>
      </section>
    </main>
  );
}
