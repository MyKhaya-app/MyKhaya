"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge } from "@/components/control-centre/badge";
import {
  CcNotice,
  CcLoadingState,
} from "@/components/control-centre/status-message";

type Source = {
  id: string;
  country_name: string;
  flag_emoji: string;
  region_name: string;
  provider: string;
  enabled: boolean;
  sync_status: "healthy" | "warning" | "failed";
  last_successful_sync: string | null;
  last_sync_error: string | null;
  cached_holiday_count: number;
};

export default function CalendarDatesPage() {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setSources(
        await platformApi.get<Source[]>("/calendar/holiday-calendars"),
      );
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function update(source: Source, enabled: boolean) {
    setBusy(source.id);
    setError("");
    try {
      await platformApi.put(`/calendar/holiday-calendars/${source.id}`, {
        enabled,
        reason: "Updating supported holiday availability",
        confirmed: true,
      });
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function sync(source: Source) {
    setBusy(source.id);
    setError("");
    try {
      await platformApi.post(`/calendar/holiday-calendars/${source.id}/sync`, {
        reason: "Manual holiday calendar sync",
        confirmed: true,
      });
      await load();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const columns: CcTableColumn<Source>[] = [
    {
      key: "country",
      header: "Country / region",
      render: (source) => (
        <span className="cc-table-primary-cell">
          <strong>{source.flag_emoji} {source.country_name}</strong>
          <small className="cc-table-subtext">{source.region_name}</small>
        </span>
      ),
    },
    { key: "provider", header: "Provider", render: (source) => source.provider },
    {
      key: "availability",
      header: "Availability",
      render: (source) => (
        <label className="cc-inline-control">
          <input type="checkbox" checked={source.enabled} disabled={busy === source.id} onChange={(event) => void update(source, event.target.checked)} />
          <span>Available to Homes</span>
        </label>
      ),
    },
    {
      key: "sync",
      header: "Sync status",
      render: (source) => (
        <span className="cc-table-primary-cell">
          <CcBadge tone={source.sync_status === "healthy" ? "success" : source.sync_status === "warning" ? "warning" : "danger"}>
            {source.sync_status === "healthy" ? "Healthy" : source.sync_status === "warning" ? "Warning" : "Failed"}
          </CcBadge>
          <small className="cc-table-subtext">{source.last_successful_sync ? `Last ${new Date(source.last_successful_sync).toLocaleString()}` : "Not synced"}</small>
          {source.last_sync_error && <small className="cc-table-subtext">{source.last_sync_error}</small>}
        </span>
      ),
    },
    { key: "cached", header: "Cached holidays", align: "right", render: (source) => source.cached_holiday_count },
    {
      key: "actions",
      header: "Actions",
      render: (source) => <button className="secondary cc-action" type="button" disabled={busy === source.id} onClick={() => void sync(source)}>{busy === source.id ? "Working…" : "Sync now"}</button>,
    },
  ];
  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Platform Settings · Calendar & Dates"
          title="Calendar & Dates"
          description="Manage public holiday sources available for Home Calendar Highlights."
          primaryAction={
            <button className="primary" type="button" onClick={() => void load()}>
              Refresh sources
            </button>
          }
        />
        <p className="cc-page-meta">
          Manage public holiday sources available for Home Calendar Highlights.
          Disabling a source prevents new Home subscriptions; cached data is
          retained.
        </p>
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {sources === null ? (
          <CcLoadingState label="Loading holiday calendars…" />
        ) : (
          <div className="platform-settings-section">
            <CcCard
              title="Supported countries"
              description="Availability is independent of provider sync health."
            >
              <CcTable
                columns={columns}
                rows={sources}
                rowKey={(source) => source.id}
                caption="Supported holiday calendars"
                emptyMessage="No holiday calendars configured."
              />
              {/*
                <div className="platform-holiday-table-head" role="row">
                  <span>Country / region</span>
                  <span>Provider</span>
                  <span>Availability</span>
                  <span>Sync</span>
                  <span>Cached dates</span>
                  <span>Actions</span>
                </div>
                {sources.map((source) => (
                  <div
                    className="platform-holiday-row"
                    role="row"
                    key={source.id}
                  >
                    <span>
                      <strong>
                        {source.flag_emoji} {source.country_name}
                      </strong>
                      <small>{source.region_name}</small>
                    </span>
                    <span>{source.provider}</span>
                    <span>
                      <label>
                        <input
                          type="checkbox"
                          checked={source.enabled}
                          disabled={busy === source.id}
                          onChange={(event) =>
                            void update(source, event.target.checked)
                          }
                        />{" "}
                        Available to Homes
                      </label>
                    </span>
                    <span>
                      <strong>{source.sync_status}</strong>
                      <small>
                        {source.last_successful_sync
                          ? `Last ${new Date(source.last_successful_sync).toLocaleString()}`
                          : "Not synced"}
                      </small>
                      {source.last_sync_error && (
                        <small>{source.last_sync_error}</small>
                      )}
                    </span>
                    <span>{source.cached_holiday_count}</span>
                    <span>
                      <button
                        type="button"
                        disabled={busy === source.id}
                        onClick={() => void sync(source)}
                      >
                        {busy === source.id ? "Working…" : "Sync now"}
                      </button>
                    </span>
                  </div>
                ))}
              </div> */}
            </CcCard>
          </div>
        )}
      </CcPage>
    </PlatformShell>
  );
}
