import { HeroActions } from "./hero-actions";
import { BellIcon, DishIcon } from "./icons";

const IMG = "/images/marketing";

export function HomeHero() {
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
          <HeroActions />
        </div>

        <div className="phones">
          {/* p2 is the largest contentful paint: fetched first. p1/p3 are hidden
              on small screens, so they load lazily (never, when hidden). */}
          <div className="phone p1">
            <HeroShot name="mykhaya-meal-plans" alt="MyKhaya Meal Plans screen with today's breakfast, lunch and dinner" lazy />
          </div>
          <div className="phone p2">
            <HeroShot name="mykhaya-home" alt="MyKhaya Home screen showing today's swimming lesson and household nudges" priority />
          </div>
          <div className="phone p3">
            <HeroShot name="mykhaya-calendar" alt="MyKhaya Calendar showing a month of shared family events" lazy />
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

/** A hero phone screenshot with a 400w variant for small screens (the phone
 *  frame is at most 250px wide, so 400w covers ~1.6x density). */
function HeroShot({ name, alt, priority = false, lazy = false }: { name: string; alt: string; priority?: boolean; lazy?: boolean }) {
  return (
    <img
      src={`${IMG}/${name}.webp`}
      srcSet={`${IMG}/${name}-400.webp 400w, ${IMG}/${name}.webp 600w`}
      sizes="(max-width: 560px) 200px, (max-width: 920px) 240px, 20vw"
      width={600}
      height={1304}
      alt={alt}
      loading={lazy ? "lazy" : "eager"}
      fetchPriority={priority ? "high" : undefined}
      decoding="async"
    />
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
