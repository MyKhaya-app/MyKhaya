"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Gift, LockKeyhole, Plus, Users } from "lucide-react";
import type { WishlistCreatePayload, WishlistSummary } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FamilyUpsell } from "@/components/family-upsell";
import { FormStatus } from "@/components/form-status";
import { FormLayout, FormSheet } from "@/components/form-layout";
import { useFormFieldErrors } from "@/components/form-field-errors";
import { useActiveHome } from "@/components/use-active-home";
import { occasionLabel } from "./occasion";
import { WISHLIST_FIELD_MESSAGES, WishlistFields, type WishlistFieldValues } from "./wishlist-fields";

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

function visibilityLabel(list: WishlistSummary): string {
  if (list.is_owner) return list.home_visible ? "Shared with Home" : "Private";
  return "Shared with Home";
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
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading Wishlists…</p>
        </main>
      </AppShellContent>
    );
  }

  if (!billingEnabled) {
    return (
      <AppShellContent>
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
      </AppShellContent>
    );
  }

  if (!moduleReleased) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <div className="page-heading">
            <div>
              <p className="eyebrow">Wishlists</p>
              <h1>Wishlists</h1>
            </div>
          </div>
          <p className="empty-mini">Wishlists isn't available for this Home yet. Please check back soon.</p>
        </main>
      </AppShellContent>
    );
  }

  const mine = homeLists.filter((list) => list.is_owner);
  const homeVisible = homeLists.filter((list) => !list.is_owner);

  function renderCard(list: WishlistSummary) {
    return (
      <Link className="card wishlists-card" href={`/wish-lists/${list.id}`} key={list.id}>
        <span className="wishlists-card-icon" aria-hidden="true">
          {list.home_visible ? <Users size={20} /> : <LockKeyhole size={18} />}
        </span>
        <span className="wishlists-card-copy">
          <strong>{list.title}</strong>
          <span className="quiet-state">
            {!list.is_owner && (
              <>
                <span className="wishlists-card-owner">{list.owner_display_name}</span> ·{" "}
              </>
            )}
            {visibilityLabel(list)} · {occasionLabel(list.occasion)} · {list.item_count} item
            {list.item_count === 1 ? "" : "s"}
          </span>
        </span>
      </Link>
    );
  }

  return (
    <AppShellContent>
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
          <h2 className="wishlists-section-heading">My wishlists</h2>
          {mine.length === 0 ? (
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
            <div className="wishlists-grid">{mine.map(renderCard)}</div>
          )}
        </section>

        {homeVisible.length > 0 && (
          <section>
            <h2 className="wishlists-section-heading">Home wishlists</h2>
            <p className="muted">Only lists their owners have chosen to share with the Home appear here.</p>
            <div className="wishlists-grid">{homeVisible.map(renderCard)}</div>
          </section>
        )}

        {sharedLists.length > 0 && (
          <section>
            <h2 className="wishlists-section-heading">Shared with me</h2>
            <div className="wishlists-grid">
              {sharedLists.map((list) => {
                return renderCard(list);
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
    </AppShellContent>
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
  const [values, setValues] = useState<WishlistFieldValues>({ title: "", occasion: "general", occasionDate: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = useFormFieldErrors(WISHLIST_FIELD_MESSAGES);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!fields.check()) {
      setError("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: WishlistCreatePayload = {
        title: values.title.trim(),
        occasion: values.occasion,
        occasion_date: values.occasionDate || null,
        description: values.description.trim() || null,
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
    <FormSheet
      title="New wishlist"
      onDismiss={onClose}
      busy={busy}
      primaryAction={
        <button type="submit" form="wishlist-create-form" disabled={busy}>
          {busy ? "Creating…" : "Create wishlist"}
        </button>
      }
    >
      <FormLayout id="wishlist-create-form" ref={fields.formRef} onSubmit={submit}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <WishlistFields
          values={values}
          errors={fields.errors}
          autoFocusTitle
          onChange={(patch, field) => {
            setValues((current) => ({ ...current, ...patch }));
            fields.clear(field);
          }}
        />
      </FormLayout>
    </FormSheet>
  );
}
