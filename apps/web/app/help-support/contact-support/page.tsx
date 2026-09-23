"use client";

import { SettingsPage } from "@/components/settings-page";

// Phase 2C ships the Help & Support hub only — the real support-request
// flow (subject/category/message form, POST /api/v1/support/tickets) is
// Phase 2E's work. This is a deliberately inert placeholder, not a mailto:
// link or any other stand-in submission path. See
// apps/web/app/help-support/page.tsx's "Contact support" quick action/card,
// which link here.
export default function ContactSupport() {
  return (
    <SettingsPage title="Contact support" description="Get help from the MyKhaya support team.">
      <section className="card details">
        <p className="quiet-state">Coming soon</p>
        <p className="muted">In-app support requests aren&apos;t available yet.</p>
      </section>
    </SettingsPage>
  );
}
