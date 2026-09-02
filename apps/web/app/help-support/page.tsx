"use client";

import Link from "next/link";
import { SettingsPage } from "@/components/settings-page";

export default function HelpSupport() {
  return (
    <SettingsPage title="Help & Support">
      <section className="card details">
        <h2>Knowledge Base</h2>
        <p className="muted">Find answers and guidance for using MyKhaya.</p>
        <p className="quiet-state">Coming soon</p>
      </section>
      <section className="card details">
        <h2>Contact Support</h2>
        <p className="muted">Get help from the MyKhaya support team.</p>
        <p className="quiet-state">Coming soon</p>
      </section>
      <div className="settings-list">
        <Link className="card" href="/service-status">
          <div>
            <h2>Service Status</h2>
            <p>Check whether MyKhaya is running normally</p>
          </div>
          <span>›</span>
        </Link>
      </div>
    </SettingsPage>
  );
}
