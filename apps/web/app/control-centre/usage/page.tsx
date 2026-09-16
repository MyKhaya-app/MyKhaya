"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcCard, CcColumns, CcSection } from "@/components/control-centre/section";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcEmptyState, CcLoadingState, CcNotice } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

type UsageReport = {
  period: { start: string; end: string; days: number; timezone: string };
  overview: { active_users: number; active_homes: number; usage_sessions: number; product_events: number };
  engagement: { dau: number; wau: number; mau: number; returning_users: number; new_users: number };
  homes: { active: number; eligible: number };
  trend: { date: string; active_users: number; active_homes: number }[];
  modules: { module: string; active_users: number; event_count: number; share_of_active_users: number }[];
  platforms: { platform: string; active_users: number; usage_sessions: number; event_count: number; share_of_global_users: number }[];
  events: { event_name: string; event_count: number }[];
};

const classifications = ["production", "all", "demo", "test", "apple_review"] as const;
const platformOptions = ["all", "web", "ios", "android"] as const;

function safeError(cause: unknown) {
  return cause instanceof ApiError ? cause.message : "Usage reporting could not be loaded.";
}
function formatNumber(value: number) { return new Intl.NumberFormat("en-GB").format(value); }
function formatPercent(value: number) { return `${value.toFixed(1)}%`; }
function labelFor(value: string) {
  return value === "apple_review" ? "Apple review" : value.charAt(0).toUpperCase() + value.slice(1);
}

export default function UsagePage() {
  const [days, setDays] = useState("30");
  const [classification, setClassification] = useState<(typeof classifications)[number]>("production");
  const [platform, setPlatform] = useState<(typeof platformOptions)[number]>("all");
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    const params = new URLSearchParams({ days, classification });
    if (platform !== "all") params.set("platform", platform);
    try { setReport(await platformApi.get<UsageReport>(`/usage/report?${params.toString()}`)); }
    catch (cause) { setError(safeError(cause)); setReport(null); }
    finally { setLoading(false); }
  }, [classification, days, platform]);
  useEffect(() => { void load(); }, [load]);

  const moduleColumns: CcTableColumn<UsageReport["modules"][number]>[] = [
    { key: "module", header: "Module", render: (row) => <strong>{row.module}</strong> },
    { key: "users", header: "Users", align: "right", render: (row) => formatNumber(row.active_users) },
    { key: "events", header: "Events", align: "right", render: (row) => formatNumber(row.event_count) },
    { key: "share", header: "User share", align: "right", render: (row) => formatPercent(row.share_of_active_users) },
  ];
  const platformColumns: CcTableColumn<UsageReport["platforms"][number]>[] = [
    { key: "platform", header: "Platform", render: (row) => <strong>{row.platform}</strong> },
    { key: "users", header: "Users", align: "right", render: (row) => formatNumber(row.active_users) },
    { key: "sessions", header: "Sessions", align: "right", render: (row) => formatNumber(row.usage_sessions) },
    { key: "share", header: "User share", align: "right", render: (row) => formatPercent(row.share_of_global_users) },
  ];
  const eventColumns: CcTableColumn<UsageReport["events"][number]>[] = [
    { key: "event", header: "Event", render: (row) => row.event_name },
    { key: "count", header: "Count", align: "right", render: (row) => formatNumber(row.event_count) },
  ];

  return <PlatformShell><CcPage wide>
    <CcPageHeader eyebrow="Product usage" title="Usage" description="Production usage reporting · Reporting days are UTC." secondaryActions={<button className="secondary" onClick={() => void load()}>Refresh</button>} />
    <form className="cc-toolbar usage-filters" onSubmit={(event) => { event.preventDefault(); void load(); }}>
      <label>Reporting period<select value={days} onChange={(event) => setDays(event.target.value)}><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select></label>
      <label>Audience<select value={classification} onChange={(event) => setClassification(event.target.value as typeof classification)}>{classifications.map((item) => <option key={item} value={item}>{labelFor(item)}</option>)}</select></label>
      <label>Platform<select value={platform} onChange={(event) => setPlatform(event.target.value as typeof platform)}>{platformOptions.map((item) => <option key={item} value={item}>{item === "all" ? "All platforms" : item.toUpperCase()}</option>)}</select></label>
      <button type="submit">Apply filters</button>
    </form>
    {error && <CcNotice tone="error">{error} <button className="secondary" onClick={() => void load()}>Retry</button></CcNotice>}
    {loading && !report ? <CcLoadingState label="Loading usage report…" /> : report && <>
      <section className="usage-metric-grid" aria-label="Overview metrics">
        {([ ["Active users", report.overview.active_users], ["Active homes", report.overview.active_homes], ["Usage sessions", report.overview.usage_sessions], ["Product events", report.overview.product_events] ] as const).map(([label, value]) => <CcCard key={label} className="usage-metric"><span>{label}</span><strong>{formatNumber(value)}</strong></CcCard>)}
      </section>
      {report.overview.product_events === 0 ? <CcEmptyState>No qualifying product activity matches these filters.</CcEmptyState> : <>
        <CcSection title="Engagement" description={`${report.period.start} to ${report.period.end} · ${report.period.timezone}`}><div className="usage-engagement-grid">{([["DAU", report.engagement.dau], ["WAU", report.engagement.wau], ["MAU", report.engagement.mau], ["Returning users", report.engagement.returning_users], ["New users", report.engagement.new_users]] as const).map(([label, value]) => <div key={label}><strong>{formatNumber(value)}</strong><span>{label}</span></div>)}</div></CcSection>
        <CcSection title="Activity trend" description="Daily active users and homes, with values available to keyboard and screen-reader users."><div className="usage-trend" role="img" aria-label="Daily active users and homes trend">{report.trend.map((day) => <div key={day.date} className="usage-trend-row"><time dateTime={day.date}>{day.date.slice(5)}</time><span style={{ width: `${Math.min(100, day.active_users * 100 / Math.max(1, report.overview.active_users))}%` }} aria-hidden="true" /><b>{formatNumber(day.active_users)} users · {formatNumber(day.active_homes)} homes</b></div>)}</div></CcSection>
        <CcColumns ratio="1-1"><CcSection title="Modules"><CcTable columns={moduleColumns} rows={report.modules} rowKey={(row) => row.module} emptyMessage="No module activity." caption="Usage by module" /></CcSection><CcSection title="Platforms"><CcTable columns={platformColumns} rows={report.platforms} rowKey={(row) => row.platform} emptyMessage="No platform activity." caption="Usage by platform" /></CcSection></CcColumns>
        <CcSection title="Event breakdown"><CcTable columns={eventColumns} rows={report.events} rowKey={(row) => row.event_name} emptyMessage="No events." caption="Usage event breakdown" /></CcSection>
        <CcNotice tone="success">Active homes: {formatNumber(report.homes.active)} of {formatNumber(report.homes.eligible)} eligible homes.</CcNotice>
      </>}
    </>}
  </CcPage></PlatformShell>;
}
