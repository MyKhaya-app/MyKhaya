import { Logo } from "../../components/logo";

export const metadata = { title: "You're offline" };

export default function OfflinePage() {
  return (
    <main className="onboarding">
      <section style={{ textAlign: "center" }}>
        <Logo />
        <p className="eyebrow">Offline</p>
        <h1>You're offline right now</h1>
        <p className="muted">
          MyKhaya can't reach the server. Check your connection and try
          again — nothing you were looking at has been lost.
        </p>
      </section>
    </main>
  );
}
