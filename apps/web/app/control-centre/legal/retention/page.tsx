"use client";

import { useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcLegalSubnav } from "@/components/control-centre/legal-subnav";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge } from "@/components/control-centre/badge";

type Entry = { category: string; purpose: string; rule: string; status: string; notes?: string };
export default function RetentionPage() { const [entries, setEntries] = useState<Entry[]>([]); const [error, setError] = useState(""); useEffect(() => { platformApi.get<{ entries: Entry[] }>("/compliance/retention").then((result) => setEntries(result.entries)).catch((cause: unknown) => setError(cause instanceof ApiError ? cause.message : "Unable to load retention information.")); }, []); return <PlatformShell><CcPage wide className="cc-retention"><CcPageHeader eyebrow="Legal & Compliance" title="Data & Retention" description="Repository-derived lifecycle information. Informational entries are clearly marked where no configurable enforcement exists." /><CcLegalSubnav />{error && <CcNotice tone="error">{error}</CcNotice>}<div className="cc-legal-table-wrap"><table className="cc-legal-table"><caption className="sr-only">Data retention categories</caption><thead><tr><th>Category</th><th>Purpose</th><th>Retention rule</th><th>Implementation</th><th>Notes</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.category}><td><strong>{entry.category}</strong></td><td>{entry.purpose}</td><td>{entry.rule}</td><td><CcBadge tone={entry.status === "enforced" ? "success" : entry.status === "configuration_dependent" ? "info" : "warning"}>{entry.status.replaceAll("_", " ")}</CcBadge></td><td>{entry.notes ?? "—"}</td></tr>)}</tbody></table></div></CcPage></PlatformShell>; }
