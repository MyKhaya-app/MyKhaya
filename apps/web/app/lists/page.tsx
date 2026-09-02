"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { ListChecks, MoreVertical, Plus } from "lucide-react";
import type { BillingStatus, HouseholdList, ListIcon } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { LIST_ICON_OPTIONS, listIconGlyph } from "./list-icons";

// Lists is a native MyKhaya module built on the HouseholdList/HouseholdListItem
// primitive introduced for Meal Plans' "Add ingredients to list" — this page
// extends that foundation rather than a second, parallel list system. See
// docs/architecture/lists.md.

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "Lists isn't available for this Home yet. Please check back soon.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function ListsPage() {
  const { activeHomeId } = useActiveHome();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [lists, setLists] = useState<HouseholdList[]>([]);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [actionsFor, setActionsFor] = useState<HouseholdList | null>(null);
  const [renaming, setRenaming] = useState<HouseholdList | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    api.billingStatus(activeHomeId).then(setBilling).catch(() => setBilling(null));
    api
      .featureMatrix(activeHomeId)
      .then((matrix) =>
        setModuleReleased(matrix.features.some((row) => row.feature === "shopping" && row.enabled)),
      )
      .catch(() => setModuleReleased(false));
  }, [activeHomeId]);

  async function load() {
    if (!activeHomeId) return;
    try {
      const result = await api.lists(activeHomeId, { q: query || undefined });
      setLists(result.items);
    } catch (cause) {
      setError(loadErrorMessage(cause, "Could not load your lists."));
    }
  }

  useEffect(() => {
    const timeout = setTimeout(() => void load(), 200);
    return () => clearTimeout(timeout);
  }, [activeHomeId, query]);

  async function removeList(list: HouseholdList) {
    if (!activeHomeId) return;
    if (!window.confirm(`Delete "${list.name}"? This will remove the list and its items.`)) return;
    try {
      await api.deleteList(activeHomeId, list.id);
      setActionsFor(null);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete that list.");
    }
  }

  if (!activeHomeId || !billing || moduleReleased === null) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading Lists…</p>
        </main>
      </AppShellContent>
    );
  }

  if (!billing.lists_enabled) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Lists</p>
              <h1>Lists</h1>
            </div>
          </div>
          <FamilyUpsell
            title="Lists"
            description="Keep groceries, packing, DIY and household bits together — shared with the whole family. Included with Family."
          />
        </main>
      </AppShellContent>
    );
  }

  if (!moduleReleased) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Lists</p>
              <h1>Lists</h1>
            </div>
          </div>
          <p className="empty-mini">Lists isn't available for this Home yet. Please check back soon.</p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page lists-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              <ListChecks size={14} aria-hidden="true" /> Lists
            </p>
            <h1>Lists</h1>
          </div>
        </div>
        <FormStatus error={error} />

        <div className="lists-toolbar">
          <input
            type="search"
            placeholder="Search lists…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search lists"
          />
          <button type="button" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden="true" /> New list
          </button>
        </div>

        {lists.length === 0 ? (
          query ? (
            <p className="empty-mini">No lists match.</p>
          ) : (
            <div className="meal-empty-state">
              <p>
                <strong>No lists yet</strong>
              </p>
              <p className="muted">Keep groceries, packing and household bits together.</p>
              <button type="button" className="secondary" onClick={() => setCreating(true)}>
                <Plus size={16} aria-hidden="true" /> Create your first list
              </button>
            </div>
          )
        ) : (
          <div className="lists-grid">
            {lists.map((list) => {
              const Glyph = listIconGlyph(list.icon);
              const complete = list.item_count > 0 && list.remaining_count === 0;
              return (
                <article className="card lists-card" key={list.id}>
                  <Link className="lists-card-body" href={`/lists/${list.id}`}>
                    <span className="lists-card-icon" aria-hidden="true">
                      <Glyph size={20} />
                    </span>
                    <span className="lists-card-copy">
                      <strong>{list.name}</strong>
                      <span className={complete ? "quiet-state lists-card-complete" : "quiet-state"}>
                        {list.item_count === 0
                          ? "No items yet"
                          : complete
                            ? `Complete · ${list.item_count} item${list.item_count === 1 ? "" : "s"}`
                            : `${list.remaining_count} remaining · ${list.item_count} item${list.item_count === 1 ? "" : "s"}`}
                      </span>
                    </span>
                  </Link>
                  <button
                    type="button"
                    className="icon-button secondary"
                    aria-label={`More actions for ${list.name}`}
                    onClick={() => setActionsFor(list)}
                  >
                    <MoreVertical size={16} aria-hidden="true" />
                  </button>
                </article>
              );
            })}
          </div>
        )}

        {actionsFor && (
          <BottomSheet title={actionsFor.name} onDismiss={() => setActionsFor(null)}>
            <div className="meal-actions-sheet">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setRenaming(actionsFor);
                  setActionsFor(null);
                }}
              >
                Rename list
              </button>
              <button type="button" className="secondary" onClick={() => void removeList(actionsFor)}>
                Delete list
              </button>
            </div>
          </BottomSheet>
        )}

        {creating && (
          <CreateListSheet
            homeId={activeHomeId}
            onClose={() => setCreating(false)}
            onCreated={async () => {
              setCreating(false);
              await load();
            }}
          />
        )}
        {renaming && (
          <RenameListSheet
            homeId={activeHomeId}
            list={renaming}
            onClose={() => setRenaming(null)}
            onRenamed={async () => {
              setRenaming(null);
              await load();
            }}
          />
        )}
      </main>
    </AppShellContent>
  );
}

function CreateListSheet({
  homeId,
  onClose,
  onCreated,
}: {
  homeId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [icon, setIcon] = useState<ListIcon | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give this list a name.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createList(homeId, { name: name.trim(), icon: icon || null });
      await onCreated();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not create this list.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="New list" onDismiss={onClose}>
      <form onSubmit={submit}>
        <label>
          List name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Groceries"
            maxLength={160}
            autoFocus
            required
          />
        </label>
        <label>
          Icon (optional)
          <select value={icon} onChange={(event) => setIcon(event.target.value as ListIcon | "")}>
            <option value="">No icon</option>
            {LIST_ICON_OPTIONS.map((row) => (
              <option key={row.key} value={row.key}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        <FormStatus error={error} />
        <button className="sheet-primary" disabled={busy}>
          {busy ? "Creating…" : "Create list"}
        </button>
      </form>
    </BottomSheet>
  );
}

function RenameListSheet({
  homeId,
  list,
  onClose,
  onRenamed,
}: {
  homeId: string;
  list: HouseholdList;
  onClose: () => void;
  onRenamed: () => Promise<void>;
}) {
  const [name, setName] = useState(list.name);
  const [icon, setIcon] = useState<ListIcon | "">(list.icon ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give this list a name.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.renameList(homeId, list.id, {
        name: name.trim(),
        icon: icon || null,
        expected_updated_at: list.updated_at,
      });
      await onRenamed();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not rename this list.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="Rename list" onDismiss={onClose}>
      <form onSubmit={submit}>
        <label>
          List name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={160}
            autoFocus
            required
          />
        </label>
        <label>
          Icon (optional)
          <select value={icon} onChange={(event) => setIcon(event.target.value as ListIcon | "")}>
            <option value="">No icon</option>
            {LIST_ICON_OPTIONS.map((row) => (
              <option key={row.key} value={row.key}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        <FormStatus error={error} />
        <button className="sheet-primary" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      </form>
    </BottomSheet>
  );
}
