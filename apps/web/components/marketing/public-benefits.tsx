import { Heart, Sun, Users } from "lucide-react";

const BENEFITS = [
  { icon: Heart, label: "Stronger family connections" },
  { icon: Users, label: "Less stress, more calm" },
  { icon: Sun, label: "More time for the moments that matter" },
] as const;

export function PublicBenefits() {
  return (
    <section
      id="lifestyle"
      className="mk-section mk-lifestyle"
      aria-labelledby="lifestyle-heading"
    >
      <div className="mk-lifestyle-panel">
        <h2 id="lifestyle-heading">
          Less organising.
          <br />
          More being together.
        </h2>
        <p>
          MyKhaya helps families share the load, stay organised and make more
          time for what really matters.
        </p>
        <ul className="mk-lifestyle-points">
          {BENEFITS.map(({ icon: Icon, label }) => (
            <li key={label}>
              <span className="mk-lifestyle-icon" aria-hidden="true">
                <Icon size={20} strokeWidth={2} />
              </span>
              {label}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
