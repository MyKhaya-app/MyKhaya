"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { relativeTime } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcBadge, toneFromStateClass, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcCard } from "@/components/control-centre/section";
import { CcStatusCard } from "@/components/control-centre/status-card";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcRecordCard, CcRecordList } from "@/components/control-centre/record-list";
import { CcActionBar } from "@/components/control-centre/action-bar";
import { CcNotice, CcLoadingState, CcEmptyState } from "@/components/control-centre/status-message";

type HealthComponent = {
  name: string;
  state: string;
  successes_24h: number;
  failures_24h: number;
  failing_devices: number;
};
type HealthCheck = {
  service: string;
  state: string;
  explanation: string;
  last_checked: string;
  last_success: string | null;
  last_failure: string | null;
  recommended_action: string | null;
  components?: HealthComponent[];
};
type HealthResponse = { overall: string; checked_at: string; services: HealthCheck[] };

const PUSH_SERVICE_NAME = "Push notifications";

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

function stateTone(state: string): CcBadgeTone {
  return toneFromStateClass(`state-${state.toLowerCase().replace(" ", "-")}`);
}

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function componentMeta(component: HealthComponent): string[] {
  const meta = [
    `${plural(component.successes_24h, "success", "successes")} (24h)`,
    `${plural(component.failures_24h, "failure", "failures")} (24h)`,
  ];
  if (component.failing_devices > 0) {
    meta.push(plural(component.failing_devices, "failing device", "failing devices"));
  }
  return meta;
}

/**
 * Every other Health service is uniform: a name, a state, an explanation,
 * some timestamps, and an optional operator action. The backend never
 * supplies a route for `recommended_action` — per the approved Phase 1
 * audit, that stays plain secondary text rather than a fabricated
 * navigation target.
 */
function ServiceHealthCard({ check }: { check: HealthCheck }) {
  return (
    <CcCard
      title={check.service}
      description={check.explanation}
      actions={<CcBadge tone={stateTone(check.state)}>{check.state}</CcBadge>}
    >
      <CcMetadataGrid dense>
        <CcMetadataItem label="Last checked">{relativeTime(check.last_checked)}</CcMetadataItem>
        <CcMetadataItem label="Last success">
          {check.last_success ? relativeTime(check.last_success) : "Never"}
        </CcMetadataItem>
        <CcMetadataItem label="Last failure">
          {check.last_failure ? relativeTime(check.last_failure) : "None"}
        </CcMetadataItem>
      </CcMetadataGrid>
      {check.recommended_action && <p className="cc-service-action">{check.recommended_action}</p>}
    </CcCard>
  );
}

/**
 * Push is the only service with real subcomponents (Production APNs,
 * Sandbox APNs, Android FCM, Web Push, Legacy iOS) — promoted to its own
 * dedicated, full-width card rather than forced into the uniform service
 * grid. See docs/architecture/platform-control-centre.md and the PCC Push
 * page (apps/web/app/control-centre/push/page.tsx) for the complementary
 * configuration/registration detail this card deliberately does not repeat.
 */
function PushHealthCard({ check }: { check: HealthCheck }) {
  return (
    <CcCard
      className="cc-health-grid-full"
      title={check.service}
      description={check.explanation}
      actions={<CcBadge tone={stateTone(check.state)}>{check.state}</CcBadge>}
    >
      {check.components && check.components.length > 0 && (
        <CcRecordList variant="grid">
          {check.components.map((component) => (
            <CcRecordCard
              key={component.name}
              title={component.name}
              badge={component.state}
              badgeTone={stateTone(component.state)}
              meta={componentMeta(component)}
            />
          ))}
        </CcRecordList>
      )}
      <CcActionBar
        actions={[
          {
            key: "view-push-diagnostics",
            label: "View push diagnostics",
            href: "/push",
            variant: "secondary",
          },
        ]}
      />
    </CcCard>
  );
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
            {data.services.length === 0 ? (
              <CcEmptyState>No health checks returned.</CcEmptyState>
            ) : (
              <div className="cc-health-grid">
                {data.services.map((check) =>
                  check.service === PUSH_SERVICE_NAME ? (
                    <PushHealthCard key={check.service} check={check} />
                  ) : (
                    <ServiceHealthCard key={check.service} check={check} />
                  )
                )}
              </div>
            )}
          </>
        )}
      </CcPage>
    </PlatformShell>
  );
}
