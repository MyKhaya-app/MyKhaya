"use client";

import { useEffect, useId, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection } from "@/components/control-centre/section";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcDialog, CcDialogActions } from "@/components/control-centre/dialog";
import { Archive, PowerOff } from "lucide-react";

type Lifecycle = "active" | "disabled" | "archived";
type LifecycleFilter = Lifecycle | "all";
type LifecycleAction = "disable" | "archive";
type Entity = "homes" | "users";

type HomeRow = {
  id: string;
  name: string;
  lifecycle: Lifecycle;
  member_count: number;
  created_at: string;
};

type UserRow = {
  id: string;
  display_name: string;
  email: string;
  lifecycle: Lifecycle;
  home_count: number;
  created_at: string;
};

type BulkFailure = { id: string; code: string; message: string };
type BulkResult = { succeeded: string[]; failed: BulkFailure[] };

const LIFECYCLE_LABEL: Record<Lifecycle, string> = {
  active: "Active",
  disabled: "Disabled",
  archived: "Archived",
};
const LIFECYCLE_TONE: Record<Lifecycle, CcBadgeTone> = {
  active: "success",
  disabled: "danger",
  archived: "neutral",
};

function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  return <CcBadge tone={LIFECYCLE_TONE[lifecycle]}>{LIFECYCLE_LABEL[lifecycle]}</CcBadge>;
}

const safeError = (error: unknown, fallback: string) =>
  error instanceof ApiError ? error.message : fallback;

/**
 * Shared list/search/filter/selection state for one cleanup tab (Homes or
 * Users). A hook rather than a generic component — the two tabs' row
 * shapes and table columns differ enough that a fully generic <T> table
 * component would need almost as much per-entity code as just rendering
 * two tables, but the data-fetching/selection logic is identical, so that
 * part is worth sharing.
 */
function useCleanupList<T extends { id: string; lifecycle: Lifecycle }>(entity: Entity) {
  const [query, setQuery] = useState("");
  const [lifecycleFilter, setLifecycleFilter] = useState<LifecycleFilter>("active");
  const [rows, setRows] = useState<T[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function load() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page_size: "100" });
      if (query.trim()) params.set("q", query.trim());
      if (lifecycleFilter !== "all") params.set("lifecycle", lifecycleFilter);
      const page = await platformApi.get<{ items: T[] }>(`/${entity}?${params.toString()}`);
      setRows(page.items);
      // A freshly loaded result set invalidates any previous selection —
      // "select-all means current visible results only" (Slice 4 §17).
      setSelected(new Set());
    } catch (cause) {
      setError(safeError(cause, `Unable to load ${entity === "homes" ? "Homes" : "users"}.`));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  // Search is opt-in (Search button/Enter, not every keystroke) but the
  // lifecycle filter re-fetches immediately — it reads as a tab, not a
  // text query.
  useEffect(() => {
    void load();
  }, [lifecycleFilter]);

  function toggle(id: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((previous) => {
      if (!rows || rows.length === 0) return previous;
      return previous.size === rows.length ? new Set() : new Set(rows.map((row) => row.id));
    });
  }

  return {
    query,
    setQuery,
    lifecycleFilter,
    setLifecycleFilter,
    rows,
    loading,
    error,
    selected,
    setSelected,
    toggle,
    toggleAll,
    load,
  };
}

type PendingBulk = { entity: Entity; action: LifecycleAction; ids: string[] };

const ACTION_COPY: Record<
  LifecycleAction,
  { verb: string; pastTense: string; homeExplain: string; userExplain: string }
> = {
  disable: {
    verb: "Disable",
    pastTense: "Disabled",
    homeExplain:
      "Disabled Homes disappear from normal operational use and members cannot use them until reactivated. Data is retained.",
    userExplain:
      "Disabled users cannot sign in until reactivated. Sessions and trusted devices are revoked; historical data and memberships are retained.",
  },
  archive: {
    verb: "Archive",
    pastTense: "Archived",
    homeExplain:
      "Archived Homes disappear from normal operational use. Data is retained and Homes can be restored individually later.",
    userExplain:
      "Archived users cannot sign in. Sessions and trusted devices are revoked; historical data and memberships are retained. Accounts can be restored individually later.",
  },
};

export default function CleanupPage() {
  const [tab, setTab] = useState<Entity>("homes");
  const homes = useCleanupList<HomeRow>("homes");
  const users = useCleanupList<UserRow>("users");
  const active = tab === "homes" ? homes : users;

  const [pending, setPending] = useState<PendingBulk | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [result, setResult] = useState<{
    entity: Entity;
    action: LifecycleAction;
    succeeded: number;
    failed: BulkFailure[];
  } | null>(null);
  const reasonFieldId = useId();
  const { guarded, modal: reauthModal } = useReauthGuard();

  function rowLabel(entity: Entity, id: string): string {
    const list = entity === "homes" ? homes.rows : users.rows;
    const row = list?.find((item) => item.id === id);
    if (!row) return id;
    return entity === "homes" ? (row as HomeRow).name : (row as UserRow).email;
  }

  const submitBulk = guarded(async () => {
    if (!pending) return;
    if (reason.trim().length < 10) {
      setDialogError("Enter at least 10 characters explaining this action.");
      return;
    }
    setBusy(true);
    setDialogError("");
    try {
      const response = await platformApi.post<BulkResult>(`/${pending.entity}/bulk-lifecycle`, {
        ids: pending.ids,
        action: pending.action,
        reason,
        confirmed: true,
      });
      setResult({
        entity: pending.entity,
        action: pending.action,
        succeeded: response.succeeded.length,
        failed: response.failed,
      });
      setPending(null);
      setReason("");
      const list = pending.entity === "homes" ? homes : users;
      await list.load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setDialogError(safeError(cause, "Unable to complete this bulk action."));
    } finally {
      setBusy(false);
    }
  });

  const homeColumns: CcTableColumn<HomeRow>[] = [
    {
      key: "select",
      header: (
        <input
          type="checkbox"
          aria-label="Select all Homes in this list"
          checked={homes.rows !== null && homes.rows.length > 0 && homes.selected.size === homes.rows.length}
          onChange={homes.toggleAll}
        />
      ),
      render: (row) => (
        <input
          type="checkbox"
          aria-label={`Select ${row.name}`}
          checked={homes.selected.has(row.id)}
          onChange={() => homes.toggle(row.id)}
        />
      ),
    },
    { key: "name", header: "Home", render: (row) => row.name },
    { key: "id", header: "Home ID", render: (row) => <code className="cc-cleanup-id">{row.id}</code> },
    { key: "lifecycle", header: "Status", render: (row) => <LifecycleBadge lifecycle={row.lifecycle} /> },
    { key: "members", header: "Members", render: (row) => row.member_count, align: "right" },
    { key: "created", header: "Created", render: (row) => new Date(row.created_at).toLocaleDateString() },
  ];

  const userColumns: CcTableColumn<UserRow>[] = [
    {
      key: "select",
      header: (
        <input
          type="checkbox"
          aria-label="Select all users in this list"
          checked={users.rows !== null && users.rows.length > 0 && users.selected.size === users.rows.length}
          onChange={users.toggleAll}
        />
      ),
      render: (row) => (
        <input
          type="checkbox"
          aria-label={`Select ${row.display_name}`}
          checked={users.selected.has(row.id)}
          onChange={() => users.toggle(row.id)}
        />
      ),
    },
    { key: "name", header: "User", render: (row) => row.display_name },
    { key: "email", header: "Email", render: (row) => row.email },
    { key: "id", header: "User ID", render: (row) => <code className="cc-cleanup-id">{row.id}</code> },
    { key: "lifecycle", header: "Status", render: (row) => <LifecycleBadge lifecycle={row.lifecycle} /> },
    { key: "homes", header: "Homes", render: (row) => row.home_count, align: "right" },
    { key: "created", header: "Created", render: (row) => new Date(row.created_at).toLocaleDateString() },
  ];

  const selectedRows = tab === "homes" ? homes.rows?.filter((row) => homes.selected.has(row.id)) ?? [] : [];
  const selectedUserRows = tab === "users" ? users.rows?.filter((row) => users.selected.has(row.id)) ?? [] : [];
  const currentSelectedLifecycles =
    tab === "homes" ? selectedRows.map((row) => row.lifecycle) : selectedUserRows.map((row) => row.lifecycle);
  const selectionSize = active.selected.size;
  // Disabled Homes/users may still be Archived, but an already-Archived
  // record should never be offered Disable — state-aware eligibility
  // (Slice 4 §3/§14) rather than only relying on the server to reject it.
  const canDisable = selectionSize > 0 && !currentSelectedLifecycles.includes("archived");
  const canArchive = selectionSize > 0;

  function openConfirm(action: LifecycleAction) {
    setPending({ entity: tab, action, ids: Array.from(active.selected) });
    setReason("");
    setDialogError("");
  }

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Administration"
          title="Account & Home cleanup"
          description="Bulk Disable or Archive test/retired Homes and Users. This tool never permanently deletes anything — every action can be reversed on the individual record's detail page."
        />

        <div className="cc-cleanup-tabs" role="tablist" aria-label="Cleanup type">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "homes"}
            className={tab === "homes" ? "cc-cleanup-tab-active" : undefined}
            onClick={() => setTab("homes")}
          >
            Homes
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "users"}
            className={tab === "users" ? "cc-cleanup-tab-active" : undefined}
            onClick={() => setTab("users")}
          >
            Users
          </button>
        </div>

        {result && result.entity === tab && (
          <div className="cc-cleanup-result">
            <CcNotice tone={result.failed.length > 0 ? "warning" : "success"}>
              {ACTION_COPY[result.action].pastTense}: {result.succeeded}
              {result.failed.length > 0 && ` — Could not update ${result.failed.length}`}
            </CcNotice>
            {result.failed.length > 0 && (
              <ul className="cc-cleanup-failures">
                {result.failed.map((failure) => (
                  <li key={failure.id}>
                    {rowLabel(result.entity, failure.id)} — {failure.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {active.error && <CcNotice tone="error">{active.error}</CcNotice>}

        <CcSection
          title={tab === "homes" ? "Homes" : "Users"}
          actions={
            <div className="cc-cleanup-toolbar">
              <input
                type="text"
                value={active.query}
                onChange={(event) => active.setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void active.load();
                  }
                }}
                placeholder={tab === "homes" ? "Search Homes by name" : "Search users by name or email"}
                aria-label={tab === "homes" ? "Search Homes" : "Search users"}
              />
              <button type="button" className="secondary" onClick={() => void active.load()}>
                Search
              </button>
              <select
                value={active.lifecycleFilter}
                onChange={(event) => active.setLifecycleFilter(event.target.value as LifecycleFilter)}
                aria-label="Lifecycle filter"
              >
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
                <option value="archived">Archived</option>
                <option value="all">All</option>
              </select>
            </div>
          }
        >
          <div className="cc-cleanup-bulk-bar">
            <span>{selectionSize} selected</span>
            <button type="button" className="secondary" disabled={!canDisable} onClick={() => openConfirm("disable")}>
              <PowerOff aria-hidden size={16} strokeWidth={2} />
              <span>Disable selected</span>
            </button>
            <button type="button" className="danger" disabled={!canArchive} onClick={() => openConfirm("archive")}>
              <Archive aria-hidden size={16} strokeWidth={2} />
              <span>Archive selected</span>
            </button>
          </div>

          {tab === "homes" ? (
            <CcTable
              columns={homeColumns}
              rows={homes.rows}
              rowKey={(row) => row.id}
              loading={homes.loading}
              emptyMessage="No Homes match this search and filter."
              caption="Homes"
            />
          ) : (
            <CcTable
              columns={userColumns}
              rows={users.rows}
              rowKey={(row) => row.id}
              loading={users.loading}
              emptyMessage="No users match this search and filter."
              caption="Users"
            />
          )}
        </CcSection>
      </CcPage>

      <CcDialog
        open={pending !== null}
        onClose={() => setPending(null)}
        title={
          pending
            ? `${ACTION_COPY[pending.action].verb} ${pending.ids.length} ${
                pending.entity === "homes" ? "Home" : "user"
              }${pending.ids.length === 1 ? "" : "s"}?`
            : ""
        }
      >
        {pending && (
          <form
            className="cc-dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submitBulk();
            }}
          >
            <div className="cc-dialog-scroll">
              {dialogError && <CcNotice tone="error">{dialogError}</CcNotice>}
              <p>{pending.entity === "homes" ? ACTION_COPY[pending.action].homeExplain : ACTION_COPY[pending.action].userExplain}</p>
              <ul className="cc-cleanup-confirm-list">
                {pending.ids.slice(0, 10).map((id) => (
                  <li key={id}>{rowLabel(pending.entity, id)}</li>
                ))}
                {pending.ids.length > 10 && <li>…and {pending.ids.length - 10} more</li>}
              </ul>
              <label htmlFor={reasonFieldId}>
                Reason for this administrative action (at least 10 characters)
              </label>
              <input
                id={reasonFieldId}
                type="text"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
                minLength={10}
                maxLength={500}
              />
            </div>
            <CcDialogActions>
              <button type="button" className="secondary" onClick={() => setPending(null)} disabled={busy}>
                Cancel
              </button>
              <button
                type="submit"
                className={pending.action === "archive" ? "danger" : undefined}
                disabled={busy || reason.trim().length < 10}
              >
                {busy ? "Working…" : `${ACTION_COPY[pending.action].verb} ${pending.ids.length}`}
              </button>
            </CcDialogActions>
          </form>
        )}
      </CcDialog>

      {reauthModal}
    </PlatformShell>
  );
}
