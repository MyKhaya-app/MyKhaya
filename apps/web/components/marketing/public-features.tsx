import { CalendarDays, ListChecks, Users } from "lucide-react";

// Deliberately only the three modules that are actually live in the
// product today (see mykhaya.module_registry — Calendar and household
// members are ReleaseState.released/core; nothing here promises a module
// that isn't shipped yet).
const FEATURES = [
  {
    icon: CalendarDays,
    title: "One calendar, everyone on it",
    description:
      "Every event, appointment and birthday your household needs — colour-coded, easy to scan, never double-booked.",
  },
  {
    icon: ListChecks,
    title: "Routines that actually stick",
    description:
      "Bins, medication, homework — the small recurring things that are easy to forget, kept visible for the whole family.",
  },
  {
    icon: Users,
    title: "A place for everyone in your home",
    description:
      "Add the people who share your home, from partners to kids, each with their own view of what matters to them.",
  },
] as const;

export function PublicFeatures() {
  return (
    <section
      className="mk-section mk-features"
      aria-labelledby="features-heading"
    >
      <div className="mk-section-heading">
        <p className="eyebrow">See it in action</p>
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
          </article>
        ))}
      </div>
    </section>
  );
}
