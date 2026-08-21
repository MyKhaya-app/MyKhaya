"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate } from "@/components/platform-format";
import type { IncidentsListResponse } from "@/components/platform-types";
import { PUBLIC_SERVICE_OPTIONS } from "@/components/platform-types";
import {
  lifecycleStateLabel,
  lifecycleStateTone,
  serviceStateLabel,
  serviceStateTone,
} from "@/components/status-incidents-logic";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcBadge } from "@/components/control-centre/badge";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcSection } from "@/components/control-centre/section";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcConfirmDialog } from "@/components/control-centre/dialog";

const LIFECYCLE_OPTIONS: { value: string; label: string }[] = [
  { value: "investigating", label: "Investigating" },
  { value: "identified", label: "Identified" },
  { value: "monitoring", label: "Monitoring" },
  { value: "resolved", label: "Resolved" },
];

export default function IncidentsPage() {
  const [data, setData] = useState<IncidentsListResponse | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<IncidentsListResponse>("/incidents"));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load incidents.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createIncident = guarded(async (formData: FormData) => {
    setError("");
    const services = PUBLIC_SERVICE_OPTIONS.filter(
      (option) => formData.get(`service_included_${option.key}`) === "on",
    ).map((option) => ({
      service: option.key,
      impact: formData.get(`service_impact_${option.key}`) as string,
    }));
    if (services.length === 0) {
      setError("Choose at least one affected service.");
      return;
    }
    const startsAt = (formData.get("starts_at") as string) || "";
    const internalNotes = (formData.get("internal_notes") as string) || "";
    try {
      await platformApi.post("/incidents", {
        title: formData.get("title"),
        message: formData.get("message"),
        services,
        lifecycle_state: formData.get("lifecycle_state"),
        starts_at: startsAt || null,
        internal_notes: internalNotes.trim() || null,
        reason: formData.get("audit_reason"),
        confirmed: true,
      });
      setMessage("Incident created.");
      setShowCreateForm(false);
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Could not create this incident.");
    }
  });

  const columns: CcTableColumn<IncidentsListResponse["incidents"][number]>[] = [
    {
      key: "title",
      header: "Incident",
      render: (row) => <Link href={`/incidents/${row.id}`}>{row.title}</Link>,
    },
    {
      key: "lifecycle",
      header: "Lifecycle",
      render: (row) => (
        <CcBadge tone={lifecycleStateTone(row.lifecycle_state)}>
          {lifecycleStateLabel(row.lifecycle_state)}
        </CcBadge>
      ),
    },
    {
      key: "services",
      header: "Affected services",
      render: (row) => row.services.map((entry) => serviceStateLabel(entry.impact) + ": " + entry.service).join(", "),
    },
    { key: "started", header: "Started", render: (row) => readableDate(row.starts_at) },
    {
      key: "status",
      header: "Status",
      render: (row) => (row.resolved_at ? `Resolved ${readableDate(row.resolved_at)}` : "Active"),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Customer-facing status"
          title="Status & Incidents"
          description="Manage the public Status page's monitored services and incidents. Only explicitly customer-facing text ever reaches that page — internal notes stay here."
          secondaryActions={
            <>
              <button className="secondary" onClick={() => void load()}>
                Refresh
              </button>
              <button onClick={() => setShowCreateForm(true)}>Create incident</button>
            </>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!data ? (
          <p role="status">Loading…</p>
        ) : (
          <>
            <CcSection title="Overall status">
              <p>
                <CcBadge tone={serviceStateTone(data.overall)}>{data.overall_message}</CcBadge>
              </p>
              <CcMetadataGrid dense>
                {data.services.map((service) => (
                  <CcMetadataItem key={service.key} label={service.name}>
                    <CcBadge tone={serviceStateTone(service.state)}>
                      {serviceStateLabel(service.state)}
                    </CcBadge>
                  </CcMetadataItem>
                ))}
              </CcMetadataGrid>
            </CcSection>

            <CcSection title="Incidents" description="Active incidents first, most recently started at the top.">
              <CcTable
                columns={columns}
                rows={data.incidents}
                rowKey={(row) => row.id}
                emptyMessage="No incidents have been recorded."
                caption="Status incidents"
              />
            </CcSection>
          </>
        )}
      </CcPage>

      <CcConfirmDialog
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title="Create incident"
        description="Choose the affected services and their customer-facing impact. The lifecycle state and message become the incident's first public timeline entry."
        confirmLabel="Create incident"
        onConfirm={createIncident}
        extraFields={
          <>
            <label>
              Incident title
              <input name="title" type="text" required minLength={3} maxLength={160} />
            </label>
            <label>
              Customer-facing description (first update)
              <textarea name="message" required minLength={3} maxLength={1000} />
            </label>
            <fieldset>
              <legend>Affected services</legend>
              <div className="cc-service-grid" role="table" aria-label="Affected services">
                <div className="cc-service-grid-header" role="row">
                  <span role="columnheader">Affected</span>
                  <span role="columnheader">Service</span>
                  <span role="columnheader">Impact</span>
                </div>
                {PUBLIC_SERVICE_OPTIONS.map((option) => (
                  <div key={option.key} className="cc-service-grid-row" role="row">
                    <label role="cell" className="cc-service-checkbox">
                      <input type="checkbox" name={`service_included_${option.key}`} />
                    </label>
                    <span role="cell" className="cc-service-name">{option.name}</span>
                    <label role="cell" className="cc-service-impact">
                      <span className="sr-only">Impact for {option.name}</span>
                      <select name={`service_impact_${option.key}`} defaultValue="partial_outage">
                        <option value="degraded_performance">Degraded Performance</option>
                        <option value="partial_outage">Partial Outage</option>
                        <option value="major_outage">Major Outage</option>
                        <option value="maintenance">Maintenance</option>
                      </select>
                    </label>
                  </div>
                ))}
              </div>
            </fieldset>
            <label>
              Initial lifecycle state
              <select name="lifecycle_state" defaultValue="investigating">
                {LIFECYCLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Start date/time (optional — leave blank to use now)
              <input type="datetime-local" name="starts_at" />
            </label>
            <label>
              Internal notes (optional, visible only to Platform Administrators)
              <textarea name="internal_notes" maxLength={2000} />
            </label>
          </>
        }
      />

      {modal}
    </PlatformShell>
  );
}
