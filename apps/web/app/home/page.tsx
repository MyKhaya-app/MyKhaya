"use client";
import { useEffect, useState } from "react";
import type { Home, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
const today = [
  ["▣", "Alyssa – Swimming", "18:00 – 19:00", "in 45 min"],
  ["🛒", "Shopping list", "Ready for your first items", "Today"],
  ["☑", "Take the bins out", "A gentle reminder", "Today"],
  ["♨", "Meal planning", "Make the week feel easier", "This week"],
];
export default function HomePage() {
  const [user, setUser] = useState<User | null>(null),
    [home, setHome] = useState<Home | null>(null);
  useEffect(() => {
    Promise.all([api.me(), api.homes()]).then(([u, h]) => {
      setUser(u);
      setHome(h[0] ?? null);
    });
  }, []);
  return (
    <AppShell>
      <main className="home-page">
        <div className="page-intro">
          <p>Good evening,</p>
          <h1>
            {user?.display_name ?? "there"} <span aria-hidden="true">👋</span>
          </h1>
          <small>Here’s what’s happening in {home?.name ?? "your Home"}</small>
        </div>
        <div className="home-grid">
          <section className="activity">
            <h2>Today</h2>
            <div className="card list-card">
              {today.map(([icon, title, detail, time]) => (
                <article key={title}>
                  <i>{icon}</i>
                  <div>
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </div>
                  <time>{time}</time>
                </article>
              ))}
            </div>
          </section>
          <section className="upcoming">
            <h2>Upcoming</h2>
            <div className="card list-card">
              <article>
                <i>♙</i>
                <div>
                  <strong>Family lunch</strong>
                  <small>Sunday · 13:00</small>
                </div>
              </article>
              <article>
                <i>▣</i>
                <div>
                  <strong>School inset day</strong>
                  <small>Friday</small>
                </div>
              </article>
              <article>
                <i>♥</i>
                <div>
                  <strong>Birthday</strong>
                  <small>Add an important date</small>
                </div>
              </article>
            </div>
          </section>
        </div>
        <section className="quick">
          <h2>Quick add</h2>
          <div className="card actions">
            <button>▣ Event</button>
            <button>☑ Task</button>
            <button>🛒 Shopping item</button>
            <button>♨ Meal</button>
            <button>▤ Note</button>
          </div>
        </section>
        <div className="summary-grid">
          <section className="card">
            <h2>
              Tasks <a href="/tasks">View all</a>
            </h2>
            <div className="empty-mini">
              Nothing urgent. A lovely place to start.
            </div>
          </section>
          <section className="card">
            <h2>
              Shopping <a href="/shopping">View list</a>
            </h2>
            <ul>
              <li>○ Milk</li>
              <li>○ Bread</li>
              <li>＋ Add item</li>
            </ul>
          </section>
          <section className="card">
            <h2>
              People <a href="/people">View everyone</a>
            </h2>
            <p>
              {home?.member_count ?? 1}{" "}
              {home?.member_count === 1 ? "person" : "people"} in this Home
            </p>
          </section>
        </div>
        <blockquote className="home-quote">
          ♥{" "}
          <span>
            Coming together is a beginning. Keeping together is progress.
          </span>
        </blockquote>
      </main>
    </AppShell>
  );
}
