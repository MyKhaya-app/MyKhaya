"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { readableDate, relativeTime, titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge, toneFromStateClass } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";

type Job = {
  id: string;
  job_type: string;
  state: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  retry_count: number;
  safe_failure_message: string | null;
  occurrence_id: string | null;
  scheduled_for: string | null;
};
type JobsResponse = { summary: Record<string, number | string | null>; items: Job[]; total: number };

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function JobsPage() {
  const [data, setData] = useState<JobsResponse | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");
  const [confirmJob, setConfirmJob] = useState<Job | null>(null);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<JobsResponse>("/jobs?page_size=50"));
    } catch (cause) {
      setError(safeError(cause, "Could not load the job queue."));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // POST /jobs/{id}/retry is guarded server-side with require_recent_auth()
  // (apps/api/mykhaya/routers/platform.py); a 403 opens PlatformReauthModal
  // and retries the same retry once verified.
  const retry = useCallback(
    (job: Job) =>
      guarded(async () => {
        setConfirmJob(null);
        setError("");
        setMessage("");
        try {
          await platformApi.post(`/jobs/${job.id}/retry`, { reason, confirmed: true });
          setMessage("The job was returned to the queue and the action was audited.");
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The job could not be retried."));
        }
      })(),
    [reason, load, guarded],
  );

  const summary = data?.summary;
  const hasFailedJobs = data?.items.some((job) => job.state === "failed") ?? false;

  const columns: CcTableColumn<Job>[] = [
    { key: "job", header: "Job", render: (row) => titleCase(row.job_type) },
    { key: "scheduled", header: "Scheduled for", render: (row) => row.scheduled_for ?? "—" },
    {
      key: "state",
      header: "State",
      render: (row) => <CcBadge tone={toneFromStateClass(`state-${row.state}`)}>{titleCase(row.state)}</CcBadge>,
    },
    { key: "started", header: "Started", render: (row) => readableDate(row.started_at) },
    { key: "duration", header: "Duration", render: (row) => (row.duration_ms === null ? "—" : `${row.duration_ms} ms`) },
    { key: "attempt", header: "Attempt", render: (row) => row.retry_count },
    {
      key: "occurrence",
      header: "Occurrence",
      render: (row) => (
        <span title={row.occurrence_id ?? undefined}>{row.occurrence_id ? row.occurrence_id.slice(-18) : "—"}</span>
      ),
    },
    { key: "failure", header: "Failure", render: (row) => row.safe_failure_message ?? "—" },
    {
      key: "action",
      header: "Action",
      render: (row) =>
        row.state === "failed" ? (
          <button disabled={reason.trim().length < 10} onClick={() => setConfirmJob(row)}>
            Retry
          </button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Background processing"
          title="Jobs & scheduler"
          secondaryActions={
            <button className="secondary" onClick={load}>
              Refresh
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        {!data ? (
          <CcLoadingState label="Loading queue and worker state…" />
        ) : (
          <>
            <section className="primary-metrics compact-metrics">
              {["queued", "running", "failed", "completed", "scheduled"].map((key) => (
                <article key={key}>
                  <strong>{summary?.[key] ?? (key === "queued" ? "Unavailable" : 0)}</strong>
                  <span>{titleCase(key)}</span>
                </article>
              ))}
            </section>

            <CcCard title="Runtime">
              <CcMetadataGrid columns="fixed-2">
                <CcMetadataItem label="Scheduler tick">
                  {relativeTime(typeof summary?.scheduler_heartbeat === "string" ? summary.scheduler_heartbeat : null)}
                </CcMetadataItem>
                <CcMetadataItem label="Worker heartbeat">
                  {relativeTime(typeof summary?.worker_heartbeat === "string" ? summary.worker_heartbeat : null)}
                </CcMetadataItem>
                <CcMetadataItem label="Next scheduled execution">
                  {readableDate(typeof summary?.next_scheduled_execution === "string" ? summary.next_scheduled_execution : null)}
                </CcMetadataItem>
                <CcMetadataItem label="Last successful execution">
                  {relativeTime(typeof summary?.last_successful_execution === "string" ? summary.last_successful_execution : null)}
                </CcMetadataItem>
              </CcMetadataGrid>
            </CcCard>

            {hasFailedJobs && (
              <CcCard title="Retry failed jobs" description="Retries require recent authentication, confirmation and are recorded in the administrative audit.">
                <CcField label="Reason for retry">
                  <input value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={500} />
                </CcField>
              </CcCard>
            )}

            <CcCard title="Recent executions">
              <CcTable
                columns={columns}
                rows={data.items}
                rowKey={(row) => row.id}
                emptyMessage="No jobs have executed yet."
                caption="Recent job executions"
              />
            </CcCard>
          </>
        )}
      </CcPage>

      {confirmJob && (
        <CcDialog open onClose={() => setConfirmJob(null)} title="Retry job">
          <div className="cc-dialog-scroll">
            <p>Retry {titleCase(confirmJob.job_type)}?</p>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setConfirmJob(null)}>
              Cancel
            </button>
            <button type="button" onClick={() => void retry(confirmJob)}>
              Retry
            </button>
          </CcDialogActions>
        </CcDialog>
      )}

      {modal}
    </PlatformShell>
  );
}
