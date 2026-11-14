import { Check, CreditCard, Gift, Users } from "lucide-react";

// The Founding Beta benefits, shown in the wide brand panel and, on phones
// (where the panel is hidden), in /register's compact Beta card.
export const BETA_BENEFITS = [
  { title: "Complimentary Ultimate for life", detail: "Full access to all features.", icon: Gift },
  { title: "No payment card required", detail: "Join without any payment details.", icon: CreditCard },
  { title: "Limited places while we test", detail: "A small number of households.", icon: Users },
] as const;

const FINAL_STEP = {
  beta: "Accept the Beta Terms and enrol your Home",
  normal: "Set up your Home",
} as const;

/** The three steps of each sign-up route. Email sign-up verifies the address
 *  next; Apple and Google have already verified it, so their middle step is
 *  setting up the account instead. */
export function signupSteps(beta: boolean, route: "email" | "provider"): string[] {
  const last = beta ? FINAL_STEP.beta : FINAL_STEP.normal;
  return route === "email"
    ? ["Create your account", "Verify your email", last]
    : ["Sign in", "Set up account", last];
}

/** The wide-screen brand panel shared by /register and the Apple/Google
 *  account choice step, so the two read as one flow. Hidden on phones by
 *  app/signup-screen.css; the other auth screens keep AuthBrandPanel. */
export function SignupBrandPanel({
  beta,
  steps,
  current,
}: {
  beta: boolean;
  steps: string[];
  /** Zero-based index of the step the person is on. */
  current: number;
}) {
  return (
    <section className="signup-brand" aria-label="About MyKhaya">
      <a className="signup-brand-logo" href="/">
        <img src="/images/mykhaya-logo.png" alt="" />
        <span>MyKhaya</span>
      </a>
      {beta ? (
        <div className="signup-brand-message">
          <span className="signup-brand-pill">Founding Beta</span>
          <h2>Help shape a calmer home.</h2>
          <p>Join a small group of households testing and improving MyKhaya.</p>
          <ul className="signup-brand-benefits">
            {BETA_BENEFITS.map(({ title, detail, icon: Icon }) => (
              <li key={title}>
                <span className="signup-brand-benefit-tile" aria-hidden="true">
                  <Icon size={20} strokeWidth={1.8} />
                </span>
                <span>
                  <strong>{title}</strong>
                  <small>{detail}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="signup-brand-message">
          <p className="signup-brand-eyebrow">Your family’s digital home</p>
          <h2>Life feels lighter when everyone knows the plan.</h2>
        </div>
      )}
      <ol className="signup-brand-steps" aria-label="Sign-up progress">
        {steps.map((step, index) => (
          <li
            key={step}
            className={index < current ? "is-done" : index === current ? "is-current" : undefined}
            aria-current={index === current ? "step" : undefined}
          >
            <span aria-hidden="true">{index < current ? <Check size={14} strokeWidth={3} /> : index + 1}</span>
            {step}
            {index < current && <span className="signup-visually-hidden"> (done)</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
