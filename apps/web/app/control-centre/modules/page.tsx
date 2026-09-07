"use client";

import { useCallback, useEffect, useState } from "react";
import { Blocks, Settings2 } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcCard } from "@/components/control-centre/section";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcActionBar, type CcAction } from "@/components/control-centre/action-bar";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";

const lifecycle = ["hidden", "internal", "beta", "early_access", "released", "deprecated"] as const;

type ModuleState = {
  key: string;
  name: string;
  description: string;
  category: string;
  dependencies: string[];
  enabled: boolean;
  release_state: string;
};

const lifecycleTone: Record<string, CcBadgeTone> = {
  hidden: "neutral",
  internal: "neutral",
  beta: "info",
  early_access: "warning",
  released: "success",
  deprecated: "danger",
};

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function ModulesPage() {
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { enabled: boolean; release_state: string }>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      const rows = await platformApi.get<ModuleState[]>("/modules");
      setModules(rows);
      setDrafts(Object.fromEntries(rows.map((row) => [row.key, { enabled: row.enabled, release_state: row.release_state }])));
    } catch (cause) {
      setError(safeError(cause, "Could not load module lifecycle state."));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // Every lifecycle change hits PUT /modules/{key}, which the backend guards
  // with require_recent_auth() (apps/api/mykhaya/routers/platform.py) — the
  // reason and confirmed:true fields, and the audit trail they produce, are
  // unchanged from before this refactor.
  const save = useCallback(
    (module: ModuleState) =>
      guarded(async () => {
        setConfirmKey(null);
        const draft = drafts[module.key];
        if (!draft) return;
        setError("");
        setMessage("");
        try {
          await platformApi.put(`/modules/${encodeURIComponent(module.key)}`, {
            ...draft,
            reason,
            confirmed: true,
          });
          setMessage(`${module.name} was updated and the change was audited.`);
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The lifecycle change could not be saved."));
        }
      })(),
    [drafts, reason, load, guarded],
  );

  const confirmModule = modules.find((module) => module.key === confirmKey) ?? null;

  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Platform lifecycle controls"
          title="Modules & Features"
          description="Every change requires recent authentication, explicit confirmation, and is recorded in the administrative audit."
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        <CcCard title="Reason for lifecycle changes" icon={Settings2}>
          <CcField
            label="Reason"
            help="Required before any lifecycle change below can be applied."
          >
            <input value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={500} required />
          </CcField>
        </CcCard>

        {!modules.length && !error ? (
          <CcLoadingState label="Loading module lifecycle state…" />
        ) : (
          modules.map((module) => {
            const draft = drafts[module.key] ?? { enabled: module.enabled, release_state: module.release_state };
            const changed = draft.enabled !== module.enabled || draft.release_state !== module.release_state;
            const actions: CcAction[] = [
              {
                key: "apply",
                label: "Apply change",
                variant: "primary",
                disabled: !changed || reason.trim().length < 10,
                onClick: () => setConfirmKey(module.key),
              },
            ];
            return (
              <CcCard
                key={module.key}
                title={
                  <>
                    {module.name} <CcBadge tone={module.enabled ? "success" : "neutral"}>{module.enabled ? "Enabled" : "Disabled"}</CcBadge>{" "}
                    <CcBadge tone={lifecycleTone[module.release_state] ?? "neutral"}>{titleCase(module.release_state)}</CcBadge>
                  </>
                }
                description={module.description}
                icon={Blocks}
              >
                <p className="cc-technical-value">{titleCase(module.category)}</p>
                {module.dependencies.length > 0 && (
                  <p className="muted">Depends on {module.dependencies.map(titleCase).join(", ")}</p>
                )}
                <CcField label="Lifecycle">
                  <select
                    value={draft.release_state}
                    onChange={(event) =>
                      setDrafts((current) => ({ ...current, [module.key]: { ...draft, release_state: event.target.value } }))
                    }
                  >
                    {lifecycle.map((state) => (
                      <option value={state} key={state}>
                        {titleCase(state)}
                      </option>
                    ))}
                  </select>
                </CcField>
                <CcField label="Enabled globally">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) =>
                      setDrafts((current) => ({ ...current, [module.key]: { ...draft, enabled: event.target.checked } }))
                    }
                  />
                </CcField>
                <CcActionBar actions={actions} />
              </CcCard>
            );
          })
        )}
      </CcPage>

      {confirmModule && (
        <CcDialog open onClose={() => setConfirmKey(null)} title="Apply lifecycle change">
          <div className="cc-dialog-scroll">
            <p>Apply the lifecycle change to {confirmModule.name}?</p>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={() => setConfirmKey(null)}>
              Cancel
            </button>
            <button type="button" onClick={() => void save(confirmModule)}>
              Apply change
            </button>
          </CcDialogActions>
        </CcDialog>
      )}

      {modal}
    </PlatformShell>
  );
}
