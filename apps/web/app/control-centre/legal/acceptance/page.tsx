"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";

type Scope = "production" | "test" | "all";
type AcceptanceRow = { user_id: string; display_name: string; email: string; account_type: "adult" | "managed_child"; documents: Array<{ key: string; display_name: string; current_version: string | null; satisfied: boolean; required: boolean; is_test?: boolean }>; last_action_at: string | null; last_action: string | null; status: "up_to_date" | "action_required" | "no_applicable_documents" };
type AcceptanceDashboard = { active_users: number; up_to_date: number; action_required: number; pending_guardian_action: number; documents: Array<{ key: string; display_name: string; current_version: string | null; is_test?: boolean }>; rows: AcceptanceRow[] };

function dateLabel(value: string | null) { return value ? new Date(value).toLocaleString() : "—"; }
function statusLabel(status: AcceptanceRow["status"]) { return status === "up_to_date" ? "Up to date" : status === "action_required" ? "Action required" : "No applicable documents"; }
function statusTone(status: AcceptanceRow["status"]): CcBadgeTone { return status === "up_to_date" ? "success" : status === "action_required" ? "warning" : "neutral"; }

export default function AcceptancePage() {
  const [data, setData] = useState<AcceptanceDashboard | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [document, setDocument] = useState("all");
  const [version, setVersion] = useState("");
  const [date, setDate] = useState("");
  const [scope] = useState<Scope>("production");
  useEffect(() => { setData(null); platformApi.get<AcceptanceDashboard>(`/compliance/acceptance?scope=${scope}`).then(setData).catch((cause: unknown) => setError(cause instanceof ApiError ? cause.message : "Unable to load legal acceptance status.")); }, [scope]);
  const rows = useMemo(() => (data?.rows ?? []).filter((row) => {
    if (filter === "up_to_date" && row.status !== "up_to_date") return false;
    if (filter === "action_required" && row.status !== "action_required") return false;
    if (filter === "adults" && row.account_type !== "adult") return false;
    if (filter === "managed_children" && row.account_type !== "managed_child") return false;
    if (document !== "all" && !row.documents.some((item) => item.key === document)) return false;
    if (version && !row.documents.some((item) => item.current_version === version)) return false;
    if (date && (!row.last_action_at || !row.last_action_at.startsWith(date))) return false;
    return true;
  }), [data, filter, document, version, date]);
  return <PlatformShell><CcPage wide className="cc-legal-acceptance"><CcPageHeader eyebrow="Legal & Compliance" title="Acceptance" description="Operational evidence of current legal actions. Acknowledgements and guardian authorisations remain distinct from contractual acceptance." /><CcLegalSubnav />{error && <CcNotice tone="error">{error}</CcNotice>}<div className="cc-legal-cards">{[["active_users", "Active users"], ["up_to_date", "Up to date"], ["action_required", "Action required"], ["pending_guardian_action", "Pending guardian action"]].map(([key, label]) => <div className="cc-legal-card" key={key}><strong>{data ? data[key as keyof AcceptanceDashboard] as number : "—"}</strong><span>{label}</span></div>)}</div><div className="cc-legal-filter-bar"><label>Status<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All statuses</option><option value="up_to_date">Up to date</option><option value="action_required">Action required</option><option value="adults">Adults</option><option value="managed_children">Managed children</option></select></label><label>Document<select value={document} onChange={(event) => setDocument(event.target.value)}><option value="all">All documents</option>{data?.documents.map((item) => <option key={item.key} value={item.key}>{item.display_name}</option>)}</select></label><label>Version<input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="e.g. 1.0" /></label><label>Date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label></div><div className="cc-legal-table-wrap"><table className="cc-legal-table"><caption className="sr-only">Legal acceptance status</caption><thead><tr><th>User</th><th>Account/session type</th><th>Terms</th><th>Privacy</th><th>Children&apos;s Privacy</th><th>Last legal action</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rows.map((row) => { const value = (keys: string[]) => row.documents.find((item) => keys.includes(item.key)); const terms = value(["terms"]); const privacy = value(["privacy"]); const children = value(["children_privacy"]); const cell = (item: typeof terms) => item ? `${item.current_version ?? "—"} · ${item.satisfied ? "current" : "required"}` : "—"; return <tr key={row.user_id}><td><Link className="table-link" href={`/users/${row.user_id}`}>{row.display_name}</Link><small>{row.email}</small></td><td>{row.account_type === "managed_child" ? "Managed child" : "Adult"}</td><td>{cell(terms)}</td><td>{cell(privacy)}</td><td>{cell(children)}</td><td>{row.last_action ? `${row.last_action} · ${dateLabel(row.last_action_at)}` : "No recorded action"}</td><td><CcBadge tone={statusTone(row.status)}>{statusLabel(row.status)}</CcBadge></td><td><Link className="table-link" href={`/legal/acceptance/${row.user_id}`}>View history</Link></td></tr>; })}</tbody></table>{!rows.length && <p className="cc-user-profile-empty">No users match these filters.</p>}</div></CcPage></PlatformShell>;
}
