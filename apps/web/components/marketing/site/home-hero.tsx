import { signupPromiseApplies, type SignupStateValue } from "@/components/public-signup";
import { BellIcon, DishIcon } from "./icons";
import { SignupLink } from "./signup-link";

const IMG = "/images/marketing";

export function HomeHero({ signupState }: { signupState: SignupStateValue }) {
  const promise = signupPromiseApplies(signupState);
  return (
    <section className="hero">
      <div className="wrap hero-grid">
        <div className="hero-copy">
          <span className="khaya">
            <b>khaya</b> <i>isiZulu &amp; isiXhosa for “home”</i>
          </span>
          <h1>
            Bring your family <em>together.</em>
          </h1>
          <p className="lede">
            Shared calendars, meal plans, nudges and lists, all in one place. MyKhaya is your family&apos;s digital
            home: less stress, and more time for what really matters.
          </p>
          <div className="hero-actions">
            <SignupLink className="btn btn-primary" state={signupState} suffix=" →" />
            <a className="btn btn-ghost" href="#features">
              Take the tour
            </a>
          </div>
          {/* Only promised when true for the current signup mode. Held (but
              invisible, so nothing shifts) until the mode is known; removed
              when sign-ups are closed. */}
          {promise !== false && (
            <ul className="ticks" style={promise === null ? { visibility: "hidden" } : undefined} aria-hidden={promise === null || undefined}>
              <li>Free to start</li>
              <li>No card required</li>
              <li>Set up in minutes</li>
            </ul>
          )}
        </div>

        <div className="phones">
          <div className="phone p1">
            <img src={`${IMG}/mykhaya-meal-plans.webp`} alt="MyKhaya Meal Plans screen with today's breakfast, lunch and dinner" loading="eager" />
          </div>
          <div className="phone p2">
            <img src={`${IMG}/mykhaya-home.webp`} alt="MyKhaya Home screen showing today's swimming lesson and household nudges" loading="eager" />
          </div>
          <div className="phone p3">
            <img src={`${IMG}/mykhaya-calendar.webp`} alt="MyKhaya Calendar showing a month of shared family events" loading="eager" />
          </div>
          <div className="chip chip-a">
            <span className="ic" style={{ background: "var(--mustard-soft)" }}>
              <BellIcon />
            </span>
            <div>
              <b>Don&apos;t forget</b>
              <small>Feed the dog · Household routine</small>
            </div>
          </div>
          <div className="chip chip-b">
            <span className="ic" style={{ background: "var(--coral-soft)" }}>
              <DishIcon />
            </span>
            <div>
              <b>Homemade Pizza</b>
              <small>Dinner at 18:00 · 3 eating</small>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function HomeStats() {
  return (
    <div className="band" aria-label="MyKhaya at a glance">
      <div className="wrap stats">
        <div className="stat"><strong>£0</strong><span>to start, on a free-forever plan</span></div>
        <div className="stat"><strong>4</strong><span>everyday tools: calendar, meals, nudges, lists</span></div>
        <div className="stat"><strong>1</strong><span>shared home for the whole household</span></div>
        <div className="stat"><strong>∞</strong><span>routines and calendar tags on Family</span></div>
      </div>
    </div>
  );
}
