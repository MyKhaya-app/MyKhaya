import Link from "next/link";
import { Bell, CalendarDays, ListChecks, UtensilsCrossed } from "lucide-react";

// Deliberately only the modules that are actually live in the product today
// (see mykhaya.module_registry — Calendar, Lists and Meal Plans are all
// ReleaseState.released; Nudges is the shipped Routines + Reminders + To-dos
// experience, see app/settings/routines-reminders). Nothing here promises a
// module that isn't shipped yet.
const FEATURES = [
  {
    icon: CalendarDays,
    title: "Calendar",
    description: "Keep everyone in sync with shared family calendars.",
  },
  {
    icon: UtensilsCrossed,
    title: "Meals",
    description: "Plan meals together and take the guesswork out of dinner.",
  },
  {
    icon: ListChecks,
    title: "Lists",
    description: "Shared shopping, to-dos and more — so nothing gets forgotten.",
  },
  {
    icon: Bell,
    title: "Nudges",
    description: "Gentle reminders to help everyone stay on track.",
  },
] as const;

export function PublicFeatures() {
  return (
    <section
      id="features"
      className="mk-section mk-features"
      aria-labelledby="features-heading"
    >
      <div className="mk-section-heading">
        <h2 id="features-heading">Made for how families actually run</h2>
      </div>
      <div className="mk-features-grid">
        {FEATURES.map(({ icon: Icon, title, description }) => (
          <article className="mk-feature-card" key={title}>
            <span className="mk-feature-icon" aria-hidden="true">
              <Icon size={24} strokeWidth={2} />
            </span>
            <h3>{title}</h3>
            <p>{description}</p>
            <Link className="mk-feature-link" href="/register">
              Learn more <span aria-hidden="true">→</span>
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
