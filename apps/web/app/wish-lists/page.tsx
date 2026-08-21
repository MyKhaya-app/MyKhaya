"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Gift, Plus } from "lucide-react";
import type { WishlistCreatePayload, WishlistOccasion, WishlistSummary } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShell } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { WISHLIST_OCCASION_OPTIONS, occasionGlyph, occasionLabel } from "./occasion";

// Wishlists is a Family-plan, per-person module — every member can keep
// their own wishlists, other Home members see them automatically, and the
// owner of a wishlist is never shown whether their own items were
// reserved/bought (enforced server-side; see wishlist_schemas.py's module
// docstring). This page never fetches or renders anything that would imply
// that data exists for the signed-in member's own wishlists. See
// docs/product/wishlists.md.

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "Wishlists isn't available for this Home yet. Please check back soon.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

interface OwnerGroup {
  ownerId: string;
  ownerName: string;
  lists: WishlistSummary[];
}

function groupByOwner(lists: WishlistSummary[]): OwnerGroup[] {
  const groups = new Map<string, OwnerGroup>();
  for (const list of lists) {
    const existing = groups.get(list.owner_user_id);
    if (existing) {
      existing.lists.push(list);
    } else {
      groups.set(list.owner_user_id, {
        ownerId: list.owner_user_id,
        ownerName: list.owner_display_name,
        lists: [list],
      });
    }
  }
  // Owner's own wishlists first, then alphabetically by owner name.
  return Array.from(groups.values()).sort((a, b) => {
    const aMine = a.lists[0]?.is_owner ? 0 : 1;
    const bMine = b.lists[0]?.is_owner ? 0 : 1;
    if (aMine !== bMine) return aMine - bMine;
    return a.ownerName.localeCompare(b.ownerName);
  });
}

export default function WishListsPage() {
  const { activeHomeId } = useActiveHome();
  const [billingEnabled, setBillingEnabled] = useState<boolean | null>(null);
  const [moduleReleased, setModuleReleased] = useState<boolean | null>(null);
  const [homeLists, setHomeLists] = useState<WishlistSummary[]>([]);
  const [sharedLists, setSharedLists] = useState<WishlistSummary[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    api
      .billingStatus(activeHomeId)
      .then((billing) => setBillingEnabled(billing.wishlists_enabled))
      .catch(() => setBillingEnabled(false));
    api
      .featureMatrix(activeHomeId)
      .then((matrix) =>
        setModuleReleased(matrix.features.some((row) => row.feature === "wish_lists" && row.enabled)),
      )
      .catch(() => setModuleReleased(false));
  }, [activeHomeId]);

  async function load() {
    if (!activeHomeId) return;
    try {
      const [homeResult, sharedResult] = await Promise.all([
        api.wishlists(activeHomeId),
        api.sharedWithMe(),
      ]);
      setHomeLists(homeResult.items);
      setSharedLists(sharedResult.items);
    } catch (cause) {
      setError(loadErrorMessage(cause, "Could not load wishlists."));
    }
  }

  useEffect(() => {
    void load();
  }, [activeHomeId]);

  if (!activeHomeId || billingEnabled === null || moduleReleased === null) {
    return (
      <AppShell>
        <main className="standard-page">
          <p role="status">Loading Wishlists…</p>
        </main>
      </AppShell>
    );
  }

  if (!billingEnabled) {
    return (
      <AppShell>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Wishlists</p>
              <h1>Wishlists</h1>
            </div>
          </div>
          <FamilyUpsell
            title="Wishlists"
            description="Keep a wishlist for every occasion and see what family members would love — without ever finding out who bought your own gifts. Included with Family."
          />
        </main>
      </AppShell>
    );
  }

  if (!moduleReleased) {
    return (
      <AppShell>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Wishlists</p>
              <h1>Wishlists</h1>
            </div>
          </div>
          <p className="empty-mini">Wishlists isn't available for this Home yet. Please check back soon.</p>
        </main>
      </AppShell>
    );
  }

  const groups = groupByOwner(homeLists);

  return (
    <AppShell>
      <main className="standard-page wishlists-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              <Gift size={14} aria-hidden="true" /> Wishlists
            </p>
            <h1>Wishlists</h1>
          </div>
          <button type="button" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden="true" /> New wishlist
          </button>
        </div>
        <FormStatus error={error} />

        <section>
          <h2 className="wishlists-section-heading">Your Home</h2>
          {groups.length === 0 ? (
            <div className="meal-empty-state">
              <p>
                <strong>No wishlists yet</strong>
              </p>
              <p className="muted">Start one for your next birthday, Christmas, or any occasion.</p>
              <button type="button" className="secondary" onClick={() => setCreating(true)}>
                <Plus size={16} aria-hidden="true" /> Create your first wishlist
              </button>
            </div>
          ) : (
            <div className="wishlists-owner-groups">
              {groups.map((group) => (
                <div className="wishlists-owner-group" key={group.ownerId}>
                  <div className="wishlists-owner-heading">
                    <Avatar id={group.ownerId} name={group.ownerName} size="sm" />
                    <strong>{group.lists[0]?.is_owner ? "Your wishlists" : group.ownerName}</strong>
                  </div>
                  <div className="wishlists-grid">
                    {group.lists.map((list) => {
                      const Glyph = occasionGlyph(list.occasion);
                      return (
                        <Link className="card wishlists-card" href={`/wish-lists/${list.id}`} key={list.id}>
                          <span className="wishlists-card-icon" aria-hidden="true">
                            <Glyph size={20} />
                          </span>
                          <span className="wishlists-card-copy">
                            <strong>{list.title}</strong>
                            <span className="quiet-state">
                              {occasionLabel(list.occasion)} · {list.item_count} item
                              {list.item_count === 1 ? "" : "s"}
                            </span>
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {sharedLists.length > 0 && (
          <section>
            <h2 className="wishlists-section-heading">Shared with me</h2>
            <div className="wishlists-grid">
              {sharedLists.map((list) => {
                const Glyph = occasionGlyph(list.occasion);
                return (
                  <Link className="card wishlists-card" href={`/wish-lists/${list.id}`} key={list.id}>
                    <span className="wishlists-card-icon" aria-hidden="true">
                      <Glyph size={20} />
                    </span>
                    <span className="wishlists-card-copy">
                      <strong>{list.title}</strong>
                      <span className="quiet-state">
                        {list.owner_display_name} · {occasionLabel(list.occasion)}
                      </span>
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {creating && (
          <CreateWishlistSheet
            homeId={activeHomeId}
            onClose={() => setCreating(false)}
            onCreated={async () => {
              setCreating(false);
              await load();
            }}
          />
        )}
      </main>
    </AppShell>
  );
}

function CreateWishlistSheet({
  homeId,
  onClose,
  onCreated,
}: {
  homeId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [occasion, setOccasion] = useState<WishlistOccasion>("general");
  const [occasionDate, setOccasionDate] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) {
      setError("Give this wishlist a title.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: WishlistCreatePayload = {
        title: title.trim(),
        occasion,
        occasion_date: occasionDate || null,
        description: description.trim() || null,
      };
      await api.createWishlist(homeId, payload);
      await onCreated();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not create this wishlist.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="New wishlist" onDismiss={onClose}>
      <form onSubmit={submit}>
        <label>
          Title
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Birthday wishlist"
            maxLength={160}
            autoFocus
            required
          />
        </label>
        <div className="meal-time-row">
          <label>
            Occasion
            <select value={occasion} onChange={(event) => setOccasion(event.target.value as WishlistOccasion)}>
              {WISHLIST_OCCASION_OPTIONS.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date (optional)
            <input
              type="date"
              value={occasionDate}
              onChange={(event) => setOccasionDate(event.target.value)}
            />
          </label>
        </div>
        <label>
          Description (optional)
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={1000}
          />
        </label>
        <FormStatus error={error} />
        <button className="sheet-primary" disabled={busy}>
          {busy ? "Creating…" : "Create wishlist"}
        </button>
      </form>
    </BottomSheet>
  );
}
