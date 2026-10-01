"use client";

import { useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge } from "@/components/control-centre/badge";
import { CalendarDays, Database, ExternalLink, Globe2, House, RefreshCw } from "lucide-react";
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
  source_url?: string | null;
  enabled: boolean;
  sync_status: "healthy" | "warning" | "failed";
  last_successful_sync: string | null;
  last_sync_error: string | null;
  cached_holiday_count: number;
};

function formatSyncDate(value: string | null) {
  if (!value) return "Not synced";
  return `Last synced ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))}`;
}

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
    {
      key: "provider",
      header: "Provider",
      render: (source) => (
        <span className="cc-table-primary-cell">
          <strong>
            {source.provider}
            {source.source_url && (
              <a className="calendar-dates-external-link" href={source.source_url} target="_blank" rel="noreferrer" aria-label={`Open ${source.provider} official source`}>
                <ExternalLink size={15} aria-hidden="true" />
              </a>
            )}
          </strong>
          <small className="cc-table-subtext">official source</small>
        </span>
      ),
    },
    {
      key: "availability",
      header: "Availability",
      render: (source) => (
        <label className="calendar-dates-toggle">
          <input type="checkbox" checked={source.enabled} disabled={busy === source.id} onChange={(event) => void update(source, event.target.checked)} />
          <span className="calendar-dates-toggle-track" aria-hidden="true"><span /></span>
          <span className="calendar-dates-toggle-copy"><strong>Available to Homes</strong><small>New Home subscriptions can use this source</small></span>
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
          <small className="cc-table-subtext">{formatSyncDate(source.last_successful_sync)}</small>
          {source.last_sync_error && <small className="cc-table-subtext">{source.last_sync_error}</small>}
        </span>
      ),
    },
    { key: "cached", header: "Cached holidays", align: "right", render: (source) => source.cached_holiday_count },
    {
      key: "actions",
      header: "Actions",
      render: (source) => (
        <button className="secondary cc-action calendar-dates-sync" type="button" disabled={busy === source.id} onClick={() => void sync(source)}>
          <RefreshCw size={16} aria-hidden="true" />
          {busy === source.id ? "Working…" : "Sync now"}
        </button>
      ),
    },
  ];
  return (
    <PlatformShell>
      <CcPage wide className="pcc-calendar-dates-page">
        <CcPageHeader
          eyebrow="Platform Settings · Calendar & Dates"
          title="Calendar & Dates"
          description="Manage public holiday sources available for Home Calendar Highlights."
          primaryAction={
            <button className="primary" type="button" onClick={() => void load()}>
              <RefreshCw size={16} aria-hidden="true" />
              Refresh sources
            </button>
          }
        />
        <div className="calendar-dates-intro-row">
          <p className="cc-page-meta calendar-dates-meta">
            Enable the countries and regions you want to make available.
            Disabling a source prevents new Home subscriptions; cached data is retained.
          </p>
          <aside className="calendar-dates-how-it-works">
            <span className="calendar-dates-info-icon"><CalendarDays size={23} aria-hidden="true" /></span>
            <div>
              <strong>How this works</strong>
              <p>Public holidays are synced from official sources and made available to Homes. You can enable or disable each source below.</p>
            </div>
          </aside>
        </div>
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {sources === null ? (
          <CcLoadingState label="Loading holiday calendars…" />
        ) : (
          <div className="platform-settings-section">
            <CcCard
              title="Supported countries"
              description="Availability is independent of provider sync health."
              icon={Globe2}
              actions={(
                <div className="calendar-dates-summary" aria-label="Holiday source summary">
                  <div className="calendar-dates-summary-tile"><Database size={22} aria-hidden="true" /><span><small>Total sources</small><strong>{sources.length}</strong></span></div>
                  <div className="calendar-dates-summary-tile"><House size={22} aria-hidden="true" /><span><small>Available to Homes</small><strong>{sources.filter((source) => source.enabled).length}</strong></span></div>
                </div>
              )}
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
