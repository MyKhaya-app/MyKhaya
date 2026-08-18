import { Home, Repeat, ShieldCheck } from "lucide-react";

const BENEFITS = [
  {
    icon: Home,
    title: "Everything in one place",
    description:
      "Your family's calendar, routines and lists together — no more juggling five different apps.",
  },
  {
    icon: Repeat,
    title: "Built around real routines",
    description:
      "Bins, medication, chores and the everyday things that actually keep a home running.",
  },
  {
    icon: ShieldCheck,
    title: "Private to your household",
    description:
      "What you add stays with your family. Nothing you share is ever public.",
  },
] as const;

export function PublicBenefits() {
  return (
    <section
      className="mk-section mk-benefits"
      aria-labelledby="benefits-heading"
    >
      <h2 id="benefits-heading" className="sr-only">
        Why families use MyKhaya
      </h2>
      <div className="mk-benefits-grid">
        {BENEFITS.map(({ icon: Icon, title, description }) => (
          <div className="mk-benefit" key={title}>
            <span className="mk-benefit-icon" aria-hidden="true">
              <Icon size={22} strokeWidth={2} />
            </span>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
