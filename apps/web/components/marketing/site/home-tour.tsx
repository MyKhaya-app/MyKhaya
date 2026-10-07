import type { CSSProperties, ReactNode } from "react";
import { BellIcon, CalendarIcon, DishIcon, FamilyIcon, HomeIcon } from "./icons";

const IMG = "/images/marketing";

type Shot = { src: string; alt: string };
type TourRow = {
  blob: string;
  iconBg: string;
  icon: ReactNode;
  eyebrow: string;
  tag?: string;
  title: string;
  intro: string;
  points: [string, string][];
  shots: Shot[];
  soon?: { title: string; text: string };
};

const ROWS: TourRow[] = [
  {
    blob: "var(--sage)",
    iconBg: "var(--tint)",
    icon: <HomeIcon />,
    eyebrow: "Home",
    title: "Your whole day on one screen.",
    intro: "Open the app and your family's day is waiting: what's on, what needs doing, and what's for dinner.",
    points: [
      ["Today at a glance.", "Events with the faces of who's involved."],
      ["Nudges that need attention.", "Overdue jobs show exactly how late they are."],
      ["Around the house.", "Add an event, invite family, or jump to meal plans, lists and wishlists in one tap."],
    ],
    shots: [
      { src: "mykhaya-home.webp", alt: "Home screen: greeting, today's events and household nudges" },
      { src: "mykhaya-home-more.webp", alt: "Home screen continued: tonight's meal, coming up and quick actions" },
    ],
  },
  {
    blob: "var(--coral)",
    iconBg: "var(--coral-soft)",
    icon: <CalendarIcon />,
    eyebrow: "Calendar",
    tag: "Free",
    title: "One calendar, everyone in it.",
    intro: "School pickups, dentist appointments and family days out, all in one shared view.",
    points: [
      ["Filter by person.", "See everyone's plans, or just one person's."],
      ["Month view with tags.", "Colour-code what matters and spot clashes early."],
      ["Tap any day.", "See who's going to what, then add an event right there."],
    ],
    shots: [
      { src: "mykhaya-calendar.webp", alt: "Calendar month view with family events" },
      { src: "mykhaya-calendar-day.webp", alt: "Day details showing school pickup and family dinner with attendees" },
    ],
  },
  {
    blob: "var(--mustard)",
    iconBg: "var(--mustard-soft)",
    icon: <DishIcon />,
    eyebrow: "Meal plans",
    title: "Dinner, decided.",
    intro: "Plan, cook and enjoy mealtimes together, without the 6pm “what are we having?” debate.",
    points: [
      ["Day or week view.", "Breakfast, lunch and dinner planned in seconds."],
      ["Saved or quick meals.", "Reuse family favourites or jot down something new."],
      ["Who's eating, who's cooking.", "Set a time, assign the cook and mark meals that make leftovers."],
    ],
    shots: [
      { src: "mykhaya-meal-plans.webp", alt: "Meal Plans: today's breakfast, lunch and dinner" },
      { src: "mykhaya-meal-edit.webp", alt: "Editing a meal: choose a saved meal, time, who's eating and who's cooking" },
    ],
  },
  {
    blob: "var(--sage)",
    iconBg: "var(--tint)",
    icon: <BellIcon />,
    eyebrow: "Nudges",
    title: "Keep track without keeping it all in your head.",
    intro: "Routines, reminders and to-dos in one place, with gentle prompts so nobody has to nag.",
    points: [
      ["Three kinds of nudge.", "Daily routines, one-off reminders and to-dos."],
      ["Personal or household.", "Keep your own jobs private, or share chores with everyone."],
      ["A daily summary.", "Notifications tell you what's still open today, and remind you before it's late."],
    ],
    shots: [
      { src: "mykhaya-nudges.webp", alt: "Nudges screen with routines, reminders and to-dos" },
      { src: "mykhaya-notifications.webp", alt: "Notifications with daily summaries and reminders" },
    ],
  },
  {
    blob: "var(--coral)",
    iconBg: "var(--coral-soft)",
    icon: <FamilyIcon />,
    eyebrow: "Family",
    tag: "Family plan",
    title: "What's happening with your people.",
    intro: "A home for the whole household, with the right access for every member.",
    points: [
      ["Roles for everyone.", "Adults, children and a Home Admin who manages the household."],
      ["Today with the family.", "Overdue jobs, tomorrow's calls and tonight's dinner in one list."],
      ["Bring in the wider family.", "Invite grandparents and close friends from outside the household."],
    ],
    shots: [{ src: "mykhaya-family.webp", alt: "Family screen with household members, family chat and today's plans" }],
    soon: { title: "Family chat", text: "Private to your family. Coming soon." },
  },
];

const ALSO: { name: string; tag: string; text: string }[] = [
  { name: "Lists", tag: "Family", text: "Shared shopping and to-do lists, so nothing gets forgotten or bought twice." },
  { name: "Gift wishlists", tag: "Family", text: "Birthdays sorted. Share wishlists with grandparents, aunts and friends." },
  { name: "Routines", tag: "Free", text: "Up to three personal routines free, and unlimited household routines on Family." },
  { name: "Calendar tags", tag: "Free", text: "Colour-code events by type. One tag free, unlimited on Family." },
  { name: "Notes", tag: "Free", text: "Somewhere for the details: wifi passwords, school codes, the plumber's number." },
  { name: "Family chat", tag: "Coming soon", text: "A private space to talk, right next to the plan." },
];

export function HomeTour() {
  return (
    <section className="showcase" id="features">
      <div className="wrap">
        <div className="section-head">
          <span className="eyebrow">Take the tour</span>
          <h2>Made for how families actually run.</h2>
          <p className="lede">Every screen is built around one question: what does my family need to know right now?</p>
        </div>

        <div className="tour">
          {ROWS.map((row) => (
            <article className="tour-row" key={row.eyebrow}>
              <div className="tour-shots" style={{ "--blob": row.blob } as CSSProperties}>
                {row.shots.map((shot) => (
                  <div className="phone" key={shot.src}>
                    <img src={`${IMG}/${shot.src}`} alt={shot.alt} loading="lazy" />
                  </div>
                ))}
                {row.soon && (
                  <div className="soon">
                    <b>{row.soon.title}</b>
                    <small>{row.soon.text}</small>
                  </div>
                )}
              </div>
              <div className="tour-copy">
                <div className="kicker">
                  <span className="ic" style={{ background: row.iconBg }}>{row.icon}</span>
                  <span className="eyebrow">{row.eyebrow}</span>
                  {row.tag && <span className="tag">{row.tag}</span>}
                </div>
                <h3>{row.title}</h3>
                <p>{row.intro}</p>
                <ul className="points">
                  {row.points.map(([lead, rest]) => (
                    <li key={lead}>
                      <div>
                        <b>{lead}</b> <span>{rest}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </div>

        <div className="also">
          <h3 className="head">Also in your home</h3>
          <div className="also-grid">
            {ALSO.map((item) => (
              <div key={item.name}>
                <div className="top">
                  <h4>{item.name}</h4>
                  <span className="tag">{item.tag}</span>
                </div>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
          <div className="ultimate">
            <div>
              <h3>Going further with Ultimate</h3>
              <p>Everything in Family, plus tools that run the rest of the house, with more premium modules on the way.</p>
            </div>
            <div className="pills">
              <span>Budget</span>
              <span>Driveway</span>
              <span>More coming</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
