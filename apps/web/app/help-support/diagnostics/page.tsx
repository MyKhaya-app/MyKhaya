"use client";

import { SettingsPage } from "@/components/settings-page";

// Phase 2C ships the Help & Support hub's compact "Helpful diagnostics"
// summary only (see apps/web/app/help-support/page.tsx) — the full
// multi-check "Run diagnostics" screen (Service connection, Internet
// connection, Notifications, App version, Device permissions, Background
// refresh, Account sync, "Share diagnostics with support") is Phase 2F's
// work. This is a deliberately inert placeholder.
export default function RunDiagnostics() {
  return (
    <SettingsPage title="Run diagnostics" description="Check your device and app settings for common issues.">
      <section className="card details">
        <p className="quiet-state">Coming soon</p>
        <p className="muted">
          A full diagnostics check isn&apos;t available yet — see the Helpful diagnostics summary
          on the Help & Support page for what we can already show you.
        </p>
      </section>
    </SettingsPage>
  );
}
