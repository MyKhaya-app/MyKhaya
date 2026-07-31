import Link from "next/link";
import { Logo } from "./logo";
export function AuthCard({
  title,
  intro,
  children,
  footer,
}: {
  title: string;
  intro: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-brand">
        <Logo />
        <p>Your family’s digital home</p>
        <blockquote>
          Life feels lighter when everyone knows the plan.
        </blockquote>
      </section>
      <section className="auth-card">
        <Link href="/" className="auth-logo">
          <Logo />
        </Link>
        <h1>{title}</h1>
        <p className="muted">{intro}</p>
        {children}
        {footer && <div className="auth-footer">{footer}</div>}
      </section>
    </main>
  );
}
