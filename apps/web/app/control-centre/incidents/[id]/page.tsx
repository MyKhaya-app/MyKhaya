"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate } from "@/components/platform-format";
import type { StatusIncidentDetail } from "@/components/platform-types";
import { PUBLIC_SERVICE_OPTIONS } from "@/components/platform-types";
import {
  lifecycleStateLabel,
  lifecycleStateTone,
  serviceStateLabel,
} from "@/components/status-incidents-logic";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcConfirmDialog } from "@/components/control-centre/dialog";

const LIFECYCLE_OPTIONS: { value: string; label: string }[] = [
  { value: "investigating", label: "Investigating" },
  { value: "identified", label: "Identified" },
  { value: "monitoring", label: "Monitoring" },
  { value: "resolved", label: "Resolved" },
];

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const router = useRouter();
  const { id } = use(params);
  const [data, setData] = useState<StatusIncidentDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showUpdateForm, setShowUpdateForm] = useState(false);
  const [showResolveDialog, setShowResolveDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<StatusIncidentDetail>(`/incidents/${encodeURIComponent(id)}`));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load this incident.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const currentImpact = new Map(data?.services.map((entry) => [entry.service, entry.impact]) ?? []);

  const addUpdate = guarded(async (formData: FormData) => {
    setError("");
    const serviceImpacts = PUBLIC_SERVICE_OPTIONS.filter((option) => currentImpact.has(option.key))
      .map((option) => {
        const chosen = formData.get(`service_impact_${option.key}`) as string | null;
        return chosen ? { service: option.key, impact: chosen } : null;
      })
      .filter((entry) => entry !== null);
    const occurredAt = (formData.get("occurred_at") as string) || "";
    const internalNotes = formData.get("internal_notes") as string | null;
    try {
      await platformApi.post(`/incidents/${encodeURIComponent(id)}/updates`, {
        message: formData.get("message"),
        lifecycle_state: formData.get("lifecycle_state"),
        occurred_at: occurredAt || null,
        service_impacts: serviceImpacts,
        resolved: formData.get("resolved") === "on",
        internal_notes: internalNotes && internalNotes.trim() ? internalNotes.trim() : null,
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Update added.");
      setShowUpdateForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not add this update.");
    }
  });

  const resolveIncident = guarded(async (formData: FormData) => {
    setError("");
    try {
      await platformApi.post(`/incidents/${encodeURIComponent(id)}/resolve`, {
        message: formData.get("message"),
        resolved_at: formData.get("resolved_at"),
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Incident resolved.");
      setShowResolveDialog(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not resolve this incident.");
    }
  });

  const deleteIncident = guarded(async (formData: FormData) => {
    setError("");
    try {
      await platformApi.delete(`/incidents/${encodeURIComponent(id)}`, {
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      router.push("/incidents");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not delete this incident.");
    }
  });

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Status incident"
          title={data?.title ?? "Incident"}
          meta={
            data && (
              <>
                <span>Started {readableDate(data.starts_at)}</span>
                <span>{data.resolved_at ? `Resolved ${readableDate(data.resolved_at)}` : "Active"}</span>
              </>
            )
          }
          secondaryActions={
            <>
              <Link href="/incidents" className="secondary">
                Back to Status &amp; Incidents
              </Link>
              <button className="secondary" onClick={() => void load()}>
                Refresh
              </button>
              {data && data.lifecycle_state !== "resolved" && (
                <>
                  <button onClick={() => setShowUpdateForm(true)}>Add update</button>
                  <button onClick={() => setShowResolveDialog(true)}>Resolve incident</button>
                </>
              )}
            </>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!data ? (
          <p role="status">Loading…</p>
        ) : (
          <>
            <CcSection title="Incident">
              <CcCard>
                <CcMetadataGrid>
                  <CcMetadataItem label="Lifecycle state">
                    <CcBadge tone={lifecycleStateTone(data.lifecycle_state)}>
                      {lifecycleStateLabel(data.lifecycle_state)}
                    </CcBadge>
                  </CcMetadataItem>
                  <CcMetadataItem label="Started">{readableDate(data.starts_at)}</CcMetadataItem>
                  <CcMetadataItem label="Resolved">
                    {data.resolved_at ? readableDate(data.resolved_at) : "Not yet resolved"}
                  </CcMetadataItem>
                  <CcMetadataItem label="Affected services" span>
                    {data.services.map((entry) => (
                      <span key={entry.service} style={{ marginRight: "0.6rem" }}>
                        {serviceStateLabel(entry.impact)}: {entry.service}
                      </span>
                    ))}
                  </CcMetadataItem>
                  {data.internal_notes && (
                    <CcMetadataItem label="Internal notes (Platform Admin only)" span>
                      {data.internal_notes}
                    </CcMetadataItem>
                  )}
                </CcMetadataGrid>
              </CcCard>
            </CcSection>

            <CcSection
              title="Public update timeline"
              description="Every entry here is (or was) visible on the public Status page, in order — updates are append-only and never edited in place."
            >
              {data.updates.length === 0 ? (
                <p className="quiet-state">No updates recorded yet.</p>
              ) : (
                <div className="record-list">
                  {data.updates.map((update) => (
                    <article key={update.id}>
                      <strong>{lifecycleStateLabel(update.lifecycle_state)}</strong>{" "}
                      <time dateTime={update.occurred_at}>{readableDate(update.occurred_at)}</time>
                      <p>{update.message}</p>
                      {update.created_by_display_name && <p>By: {update.created_by_display_name}</p>}
                    </article>
                  ))}
                </div>
              )}
            </CcSection>

            <CcSection title="Danger zone" description="Delete only test, duplicate, or mistakenly created incidents. Resolve genuine customer-facing incidents instead.">
              <CcCard>
                <button className="danger" type="button" onClick={() => setShowDeleteDialog(true)}>
                  Delete incident
                </button>
              </CcCard>
            </CcSection>
          </>
        )}
      </CcPage>

      {data && (
        <CcConfirmDialog
          open={showUpdateForm}
          onClose={() => setShowUpdateForm(false)}
          title="Add incident update"
          description="Appends a new entry to this incident's public timeline. Change a service's impact here only if it has actually changed since the last update."
          confirmLabel="Add update"
          onConfirm={addUpdate}
          extraFields={
            <>
              <label>
                Public update text
                <textarea name="message" required minLength={3} maxLength={1000} />
              </label>
              <label>
                Lifecycle state
                <select name="lifecycle_state" defaultValue={data.lifecycle_state}>
                  {LIFECYCLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Update timestamp (optional — leave blank to use now)
                <input type="datetime-local" name="occurred_at" />
              </label>
              {data.services.length > 0 && (
                <fieldset>
                  <legend>Service impact (leave as-is if unchanged)</legend>
                  {data.services.map((entry) => (
                    <label key={entry.service}>
                      {entry.service}
                      <select name={`service_impact_${entry.service}`} defaultValue={entry.impact}>
                        <option value="operational">Operational</option>
                        <option value="degraded_performance">Degraded Performance</option>
                        <option value="partial_outage">Partial Outage</option>
                        <option value="major_outage">Major Outage</option>
                        <option value="maintenance">Maintenance</option>
                      </select>
                    </label>
                  ))}
                </fieldset>
              )}
              <label className="check-row">
                <input type="checkbox" name="resolved" />
                Mark this incident Resolved
              </label>
              <label>
                Internal notes (optional, replaces the current note if set)
                <textarea name="internal_notes" maxLength={2000} defaultValue={data.internal_notes ?? ""} />
              </label>
            </>
          }
        />
      )}

      {data && data.lifecycle_state !== "resolved" && (
        <CcConfirmDialog
          open={showResolveDialog}
          onClose={() => setShowResolveDialog(false)}
          title="Resolve incident"
          description="This appends a final public Resolved update and removes the incident from Current incidents while preserving its history."
          confirmLabel="Resolve incident"
          onConfirm={resolveIncident}
          extraFields={
            <>
              <p>
                <strong>{data.title}</strong>
                <br />
                {data.services.map((entry) => `${serviceStateLabel(entry.impact)}: ${entry.service}`).join(" · ")}
              </p>
              <label>
                Final public update
                <textarea
                  name="message"
                  required
                  minLength={3}
                  maxLength={1000}
                  defaultValue="This incident has been resolved and services have returned to normal."
                />
              </label>
              <label>
                Resolved date and time
                <input name="resolved_at" type="datetime-local" required defaultValue={datetimeLocalNow()} />
              </label>
            </>
          }
        />
      )}

      {data && (
        <CcConfirmDialog
          open={showDeleteDialog}
          onClose={() => setShowDeleteDialog(false)}
          title="Delete incident permanently?"
          description="This permanently removes the incident and its update timeline. Use this for test incidents, duplicates, or incidents created in error; resolve genuine historical incidents instead."
          confirmLabel="Delete permanently"
          variant="destructive"
          onConfirm={deleteIncident}
          extraFields={
            <p>
              <strong>{data.title}</strong>
              <br />
              Started {readableDate(data.starts_at)} · {lifecycleStateLabel(data.lifecycle_state)}
              <br />
              {data.services.map((entry) => `${serviceStateLabel(entry.impact)}: ${entry.service}`).join(" · ")}
            </p>
          }
        />
      )}

      {modal}
    </PlatformShell>
  );
}

function datetimeLocalNow(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}
