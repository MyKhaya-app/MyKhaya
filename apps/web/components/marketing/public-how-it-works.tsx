const STEPS = [
  {
    title: "Create your Home",
    description: "Sign up free in under a minute — no card required.",
  },
  {
    title: "Add your family",
    description:
      "Invite the people who share your home, or keep it just for you.",
  },
  {
    title: "Get organised, together",
    description: "Calendar, routines and lists everyone can see and trust.",
  },
] as const;

export function PublicHowItWorks() {
  return (
    <section className="mk-section mk-how" aria-labelledby="how-heading">
      <div className="mk-section-heading">
        <p className="eyebrow">Getting started</p>
        <h2 id="how-heading">Up and running in three steps</h2>
      </div>
      <ol className="mk-how-grid">
        {STEPS.map((step, index) => (
          <li className="mk-how-step" key={step.title}>
            <span className="mk-how-number" aria-hidden="true">
              {index + 1}
            </span>
            <h3>{step.title}</h3>
            <p>{step.description}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
