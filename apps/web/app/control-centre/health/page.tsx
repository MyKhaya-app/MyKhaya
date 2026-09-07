"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge, toneFromStateClass, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";

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

  return (
    <PlatformShell>
      <CcPage>
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
            {data.services.map((check) => (
              <CcCard
                key={check.service}
                title={
                  <>
                    {check.service} <CcBadge tone={stateTone(check.state)}>{check.state}</CcBadge>
                  </>
                }
                description={check.explanation}
                icon={Activity}
              >
                <CcMetadataGrid>
                  {check.last_success && (
                    <CcMetadataItem label="Last successful check">{relativeTime(check.last_success)}</CcMetadataItem>
                  )}
                  {check.last_failure && (
                    <CcMetadataItem label="Last failure">{relativeTime(check.last_failure)}</CcMetadataItem>
                  )}
                </CcMetadataGrid>
                {check.recommended_action && (
                  <p className="operator-action">
                    <strong>Operator action:</strong> {check.recommended_action}
                  </p>
                )}
              </CcCard>
            ))}
          </>
        )}
      </CcPage>
    </PlatformShell>
  );
}
