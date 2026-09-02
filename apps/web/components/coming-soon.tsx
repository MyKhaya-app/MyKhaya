import Link from "next/link";
import { AppShellContent } from "./app-shell";
export function ComingSoon({ name, icon }: { name: string; icon: string }) {
  return (
    <AppShellContent>
      <main className="coming">
        <div aria-hidden="true">{icon}</div>
        <p className="eyebrow">A little more time in the oven</p>
        <h1>{name} is coming soon</h1>
        <p>We’re shaping this carefully so it makes life together simpler.</p>
        <Link className="button" href="/home">
          Back Home
        </Link>
      </main>
    </AppShellContent>
  );
}
