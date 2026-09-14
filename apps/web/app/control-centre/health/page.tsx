"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge, toneFromStateClass, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";

type HealthCheck = {
  service: string;
  state: string;
  explanation: string;
  last_checked: string;
  last_success: string | null;
  last_failure: string | null;
  recommended_action: string | null;
};
type HealthResponse = { overall: string; checked_at: string; services: HealthCheck[] };

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

function stateTone(state: string): CcBadgeTone {
  return toneFromStateClass(`state-${state.toLowerCase().replace(" ", "-")}`);
}

export default function HealthPage() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await platformApi.get<HealthResponse>("/health"));
    } catch (cause) {
      setError(safeError(cause, "Health checks are unavailable."));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const columns: CcTableColumn<HealthCheck>[] = [
    {
      key: "service",
      header: "Service / dependency",
      render: (check) => (
        <span className="cc-table-primary-cell">
          <strong>{check.service}</strong>
          <small className="cc-table-subtext">{check.explanation}</small>
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (check) => <CcBadge tone={stateTone(check.state)}>{check.state}</CcBadge>,
    },
    {
      key: "checked",
      header: "Last checked",
      render: (check) => relativeTime(check.last_checked),
    },
    {
      key: "history",
      header: "Recent history",
      render: (check) => (
        <span className="cc-table-primary-cell">
          <small className="cc-table-subtext">Success: {check.last_success ? relativeTime(check.last_success) : "Never"}</small>
          <small className="cc-table-subtext">Failure: {check.last_failure ? relativeTime(check.last_failure) : "None"}</small>
        </span>
      ),
    },
    {
      key: "action",
      header: "Operator action",
      render: (check) => check.recommended_action ?? "None required",
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Live diagnostics"
          title="Health"
          secondaryActions={
            <button className="secondary" onClick={load} disabled={loading}>
              Run checks
            </button>
          }
        />
        {error && <CcNotice tone="error">Health checks are unavailable: {error}</CcNotice>}
        {!data ? (
          <CcLoadingState label="Running platform checks…" />
        ) : (
          <>
            <CcStatusCard
              tone={stateTone(data.overall)}
              status={data.overall}
              description={`Checked ${relativeTime(data.checked_at)}`}
            />
            <CcTable
              columns={columns}
              rows={data.services}
              rowKey={(check) => check.service}
              caption="Platform health checks"
              emptyMessage="No health checks returned."
            />
          </>
        )}
      </CcPage>
    </PlatformShell>
  );
}
