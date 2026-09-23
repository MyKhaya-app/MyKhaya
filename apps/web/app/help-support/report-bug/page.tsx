"use client";

import { SettingsPage } from "@/components/settings-page";

// Phase 2C ships the Help & Support hub only — the real submission flow
// (form, screenshot attachment, diagnostics toggle, POST /api/v1/support/tickets)
// is Phase 2D's work. This is a deliberately inert placeholder: no form
// fields, no fake request, nothing that looks functional. See
// apps/web/app/help-support/page.tsx's "Report a bug" quick action/card,
// which link here.
export default function ReportBug() {
  return (
    <SettingsPage title="Report a bug" description="Help us fix issues faster by sharing what happened.">
      <section className="card details">
        <p className="quiet-state">Coming soon</p>
        <p className="muted">In-app bug reporting isn&apos;t available yet.</p>
      </section>
    </SettingsPage>
  );
}
