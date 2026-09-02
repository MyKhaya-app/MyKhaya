"use client";

import { useEffect, useState } from "react";
import { SettingsPage } from "@/components/settings-page";
import { openExternalUrl } from "@/components/open-external-url";

// The service status URL is a canonical, PCC-managed operational setting
// (mykhaya.platform_settings.SETTINGS_SCHEMA's service_status_url) — never
// hardcoded here. Only the consumer-safe allow-listed endpoint is used,
// never the privileged /platform/settings surface.
function useServiceStatusUrl(): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/config/public", { cache: "no-store" })
      .then((response) => (response.ok ? (response.json() as Promise<{ service_status_url: string | null }>) : null))
      .then((payload) => setUrl(payload?.service_status_url ?? null))
      .catch(() => setUrl(null));
  }, []);

  return url;
}

export default function HelpSupport() {
  const serviceStatusUrl = useServiceStatusUrl();

  return (
    <SettingsPage title="Help & Support">
      <div className="card-stack">
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
        {serviceStatusUrl ? (
          <a
            className="card"
            href={serviceStatusUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => {
              event.preventDefault();
              void openExternalUrl(serviceStatusUrl);
            }}
          >
            <div>
              <h2>Service Status</h2>
              <p>Check whether MyKhaya is running normally</p>
            </div>
            <span>›</span>
          </a>
        ) : (
          <div className="card" aria-disabled="true">
            <div>
              <h2>Service Status</h2>
              <p>Not available right now</p>
            </div>
          </div>
          )}
      </div>
    </SettingsPage>
  );
}
