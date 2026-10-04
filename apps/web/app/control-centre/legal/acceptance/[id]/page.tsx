"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import { CcNotice } from "@/components/control-centre/status-message";

type History = { display_name: string; email: string; account_type: string; current_status: Array<{ display_name: string; action_verb: string; current_version: string | null; satisfied: boolean }>; history: Array<{ id: string; display_name: string; document_id: string; version: string; version_id: string; record_type: string; context: string; platform: string; created_at: string; child_profile_id: string | null; is_test?: boolean }> };
function actionLabel(type: string) { return type === "user_acceptance" ? "Accepted" : type === "user_acknowledgement" ? "Acknowledged" : type === "guardian_authorisation" ? "Guardian authorisation recorded" : "Child acknowledgement"; }
export default function AcceptanceHistoryPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<History | null>(null); const [error, setError] = useState("");
  useEffect(() => { platformApi.get<History>(`/compliance/acceptance/${encodeURIComponent(id)}`).then(setData).catch((cause: unknown) => setError(cause instanceof ApiError ? cause.message : "Unable to load legal history.")); }, [id]);
  return <PlatformShell><CcPage wide className="cc-legal-history"><CcPageHeader eyebrow="Legal & Compliance" title={data ? `${data.display_name}'s legal history` : "Legal history"} description={data?.email ?? "Immutable records associated with this user."} /><CcLegalSubnav />{error && <CcNotice tone="error">{error}</CcNotice>}{data && <><section className="cc-legal-card"><strong>{data.account_type === "managed_child" ? "Managed child" : "Adult"}</strong><span>Account/session type</span></section><section className="cc-user-profile-card"><div className="cc-user-profile-card-heading"><h2>Current status</h2></div>{data.current_status.map((item) => <p key={item.display_name}><strong>{item.display_name}</strong> · {item.action_verb} · version {item.current_version ?? "—"} · {item.satisfied ? "Current" : "Action required"}</p>)}</section><section className="cc-user-profile-card"><div className="cc-user-profile-card-heading"><h2>Immutable history</h2></div>{data.history.length ? data.history.map((item) => <article className="cc-legal-history-item" key={item.id}><h3>{item.display_name} · v{item.version}</h3><p>{actionLabel(item.record_type)} · {new Date(item.created_at).toLocaleString()} · {item.context} · {item.platform}</p><p className="muted">Record {item.id}{item.child_profile_id ? ` · Child profile ${item.child_profile_id}` : ""}</p><Link className="table-link" href={`/legal/documents/${item.document_id}/versions/${item.version_id}`}>View exact version</Link></article>) : <p className="cc-user-profile-empty">No legal action has been recorded.</p>}</section></>}</CcPage></PlatformShell>;
}
