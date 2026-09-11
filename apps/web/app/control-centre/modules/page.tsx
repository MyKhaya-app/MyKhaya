"use client";

import { useCallback, useEffect, useState } from "react";
import { ToggleLeft, ToggleRight } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { titleCase } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection } from "@/components/control-centre/section";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcDialog, CcDialogActions, CcConfirmDialog } from "@/components/control-centre/dialog";

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

// Truthful operator-facing classification — deliberately per-module rather
// than a mechanical pass-through of the registry's own `category` field
// (Notifications is registry category "Communication", External sharing is
// "Experimental" — neither reads correctly to an operator scanning this
// table). Every module PCC's /modules endpoint returns is one of these
// three; nothing here invents a state the backend doesn't already carry
// (see mykhaya.module_registry.ModuleDefinition.home_admin_manageable,
// which is what actually makes Notifications/External sharing not
// ordinary Home modules).
function moduleType(module: ModuleState): string {
  if (module.key === "notifications") return "Infrastructure";
  if (module.key === "external_sharing") return "Calendar capability";
  return "Family module";
}

function dependencyList(module: ModuleState): string {
  return module.dependencies.length > 0 ? module.dependencies.map(titleCase).join(", ") : "—";
}

function safeError(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function ModulesPage() {
  const [modules, setModules] = useState<ModuleState[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [manageKey, setManageKey] = useState<string | null>(null);
  const [draftLifecycle, setDraftLifecycle] = useState("");
  const [draftEnabled, setDraftEnabled] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const { guarded, modal } = useReauthGuard();

  const load = useCallback(async () => {
    setError("");
    try {
      setModules(await platformApi.get<ModuleState[]>("/modules"));
    } catch (cause) {
      setError(safeError(cause, "Could not load module lifecycle state."));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const manageModule = modules?.find((module) => module.key === manageKey) ?? null;
  const changed =
    manageModule !== null &&
    (draftLifecycle !== manageModule.release_state || draftEnabled !== manageModule.enabled);

  function openManage(module: ModuleState) {
    setManageKey(module.key);
    setDraftLifecycle(module.release_state);
    setDraftEnabled(module.enabled);
    setMessage("");
  }
  function closeManage() {
    setManageKey(null);
    setConfirming(false);
  }

  // Every lifecycle change hits PUT /modules/{key}, which the backend guards
  // with require_recent_auth() (apps/api/mykhaya/routers/platform.py) — the
  // reason and confirmed:true fields, and the audit trail they produce, are
  // unchanged from before this refactor.
  const save = useCallback(
    (module: ModuleState, reason: string) =>
      guarded(async () => {
        setError("");
        setMessage("");
        try {
          await platformApi.put(`/modules/${encodeURIComponent(module.key)}`, {
            enabled: draftEnabled,
            release_state: draftLifecycle,
            reason,
            confirmed: true,
          });
          setMessage(`${module.name} was updated and the change was audited.`);
          closeManage();
          await load();
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 403) throw cause;
          setError(safeError(cause, "The lifecycle change could not be saved."));
          setConfirming(false);
        }
      })(),
    [draftEnabled, draftLifecycle, load, guarded],
  );

  const columns: CcTableColumn<ModuleState>[] = [
    {
      key: "module",
      header: "Module",
      render: (module) => (
        <>
          <strong>{module.name}</strong>
          {module.description && <p className="muted cc-table-subtext">{module.description}</p>}
        </>
      ),
    },
    { key: "type", header: "Type", render: (module) => moduleType(module) },
    {
      key: "lifecycle",
      header: "Lifecycle",
      render: (module) => (
        <CcBadge tone={lifecycleTone[module.release_state] ?? "neutral"}>
          {titleCase(module.release_state)}
        </CcBadge>
      ),
    },
    {
      key: "platform_state",
      header: "Platform state",
      render: (module) => (
        <CcBadge tone={module.enabled ? "success" : "neutral"}>
          {module.enabled ? "Enabled" : "Disabled"}
        </CcBadge>
      ),
    },
    { key: "dependencies", header: "Dependencies", render: (module) => dependencyList(module) },
    {
      key: "actions",
      header: "",
      render: (module) => (
        <button type="button" className="secondary" onClick={() => openManage(module)}>
          Manage
        </button>
      ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Platform lifecycle controls"
          title="Modules & Features"
          description="Every change requires recent authentication, explicit confirmation, and is recorded in the administrative audit."
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        {message && <CcNotice tone="success">{message}</CcNotice>}

        <CcSection>
          {modules === null && !error ? (
            <CcLoadingState label="Loading module lifecycle state…" />
          ) : (
            <CcTable
              columns={columns}
              rows={modules}
              rowKey={(module) => module.key}
              caption="Modules & Features"
              emptyMessage="No modules found."
            />
          )}
        </CcSection>
      </CcPage>

      {manageModule && (
        <CcDialog
          open={!confirming}
          onClose={closeManage}
          title={`Manage ${manageModule.name}`}
        >
          <div className="cc-dialog-scroll">
            <p className="muted">{manageModule.description}</p>
            <p className="cc-technical-value">{moduleType(manageModule)}</p>
            <p className="muted">Depends on {dependencyList(manageModule)}</p>
            <p className="muted">
              Current: {titleCase(manageModule.release_state)} ·{" "}
              {manageModule.enabled ? "Enabled" : "Disabled"}
            </p>
            <CcField label="Lifecycle">
              <select value={draftLifecycle} onChange={(event) => setDraftLifecycle(event.target.value)}>
                {lifecycle.map((state) => (
                  <option value={state} key={state}>
                    {titleCase(state)}
                  </option>
                ))}
              </select>
            </CcField>
            <div className="cc-field">
              {/* Not a CcField: that would associate this button with a
                  <label htmlFor>, which overrides its own accessible name
                  ("Enable"/"Disable") with the label text instead — this
                  keeps the same visual label-above-control layout without
                  that ARIA-naming collision. */}
              <p>Platform enabled</p>
              <button
                type="button"
                className="secondary cc-action"
                onClick={() => setDraftEnabled((current) => !current)}
              >
                {draftEnabled ? (
                  <ToggleLeft aria-hidden size={16} strokeWidth={2} />
                ) : (
                  <ToggleRight aria-hidden size={16} strokeWidth={2} />
                )}
                <span>{draftEnabled ? "Disable" : "Enable"}</span>
              </button>
            </div>
          </div>
          <CcDialogActions>
            <button type="button" className="secondary" onClick={closeManage}>
              Cancel
            </button>
            <button type="button" disabled={!changed} onClick={() => setConfirming(true)}>
              Apply change
            </button>
          </CcDialogActions>
        </CcDialog>
      )}

      {manageModule && (
        <CcConfirmDialog
          open={confirming}
          onClose={() => setConfirming(false)}
          title={`Apply changes to ${manageModule.name}`}
          description={
            <>
              Module: {manageModule.name}
              <br />
              Lifecycle: {titleCase(manageModule.release_state)} → {titleCase(draftLifecycle)}
              <br />
              Platform state: {manageModule.enabled ? "Enabled" : "Disabled"} →{" "}
              {draftEnabled ? "Enabled" : "Disabled"}
            </>
          }
          confirmLabel="Apply change"
          onConfirm={(formData) => {
            const rawReason = formData.get("audit_reason");
            const reason = typeof rawReason === "string" ? rawReason : "";
            return save(manageModule, reason);
          }}
        />
      )}

      {modal}
    </PlatformShell>
  );
}
