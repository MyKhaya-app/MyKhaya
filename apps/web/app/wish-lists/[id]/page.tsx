"use client";

import { FormEvent, use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft, Copy, ExternalLink, Image as ImageIcon, LockKeyhole, MoreVertical, Plus, Share2, Trash2, Users } from "lucide-react";
import type {
  GuestShareCreateResponse,
  ShareCreatePayload,
  ShareListItem,
  User,
  WishlistDetail,
  WishlistItemCreatePayload,
  WishlistItemOwner,
  WishlistItemUpdatePayload,
  WishlistItemViewer,
  WishlistLinkPreview,
  WishlistOwnerDetail,
  WishlistUpdatePayload,
} from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { FormField, FormLayout, FormRow, FormSheet } from "@/components/form-layout";
import { useFormFieldErrors, type FormFieldErrors, type FormFieldMessages } from "@/components/form-field-errors";
import { openExternalUrl } from "@/components/open-external-url";
import { useActiveHome } from "@/components/use-active-home";
import { occasionGlyph, occasionLabel } from "../occasion";
import { WISHLIST_FIELD_MESSAGES, WishlistFields, type WishlistFieldValues } from "../wishlist-fields";

// Wishlist detail — the one non-negotiable rule for this whole page: an
// owner must never see, anywhere in this component tree, whether their own
// items are reserved/bought or by whom. `isOwnerDetail` below is the single
// place that decides which of the two response shapes (owner vs viewer) is
// in play; every render path downstream of it either has zero access to
// reservation fields (owner shape has none at all, so it's a compile error
// to reference them) or renders the viewer shape, never both. See
// wishlist_schemas.py's module docstring for the backend half of this
// guarantee.

function isOwnerDetail(detail: WishlistDetail, currentUserId: string): detail is WishlistOwnerDetail {
  return detail.owner_user_id === currentUserId;
}

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That wishlist could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

function formatPrice(price: string | null, currency: string | null): string | null {
  if (!price) return null;
  return currency ? `${currency} ${price}` : price;
}

function domainFor(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// Below this, a "loaded" image is still treated as unusable and the icon
// fallback is shown instead — some retailers serve a genuine-but-blank
// lazy-load stand-in graphic (a 1x1 tracking pixel, or a small blank/grey
// placeholder swapped for the real photo only after client-side JS runs) as
// their static og:image/JSON-LD image. Such an image loads successfully (no
// onError) but, stretched via object-fit: cover across the 76px box, reads
// as a flat pale rectangle — exactly the "blank placeholder bar" symptom.
// naturalWidth/naturalHeight below the size a real product photo would ever
// be is the cheapest reliable signal that this happened.
const _MIN_USABLE_IMAGE_DIMENSION_PX = 8;

function WishlistImage({ src, alt }: { src: string | null; alt: string }) {
  const [status, setStatus] = useState<"loading" | "loaded" | "unusable">("loading");

  // A new src (including going back to null) always starts a fresh
  // loading/settle cycle rather than keeping a stale prior status around.
  useEffect(() => {
    setStatus(src ? "loading" : "unusable");
  }, [src]);

  if (!src || status === "unusable") {
    return (
      <span className="wishlists-item-image wishlists-item-image-placeholder" aria-hidden="true">
        <ImageIcon size={24} />
      </span>
    );
  }
  return (
    <span className={`wishlists-item-image${status === "loading" ? " wishlists-item-image-loading" : ""}`}>
      <img
        src={src}
        alt={alt}
        style={status === "loading" ? { visibility: "hidden" } : undefined}
        onLoad={(event) => {
          const img = event.currentTarget;
          if (
            img.naturalWidth < _MIN_USABLE_IMAGE_DIMENSION_PX ||
            img.naturalHeight < _MIN_USABLE_IMAGE_DIMENSION_PX
          ) {
            setStatus("unusable");
            return;
          }
          setStatus("loaded");
        }}
        onError={() => setStatus("unusable")}
      />
    </span>
  );
}

// --- Link preview: shared between AddItemSheet and EditItemSheet ----------
//
// "Found" means ANY of title/image_url/price/description came back non-null
// — checking only image_url/title (as this used to) silently under-reported
// a price-only or description-only result as "No preview details were
// available", which is just as dishonest in the other direction as claiming
// success for nothing useful. previewState is a real, distinct state
// (idle/loading/found/empty/error) rather than one message string standing
// in for two different outcomes, so callers (and tests) can target each
// state unambiguously.

type LinkPreviewState = "idle" | "loading" | "found" | "empty" | "error";

function useLinkPreview(args: {
  homeId: string;
  name: string;
  setName: (value: string) => void;
  imageUrl: string;
  setImageUrl: (value: string) => void;
  price: string;
  setPrice: (value: string) => void;
  currency: string;
  setCurrency: (value: string) => void;
}) {
  const { homeId, name, setName, imageUrl, setImageUrl, price, setPrice, currency, setCurrency } = args;
  const [previewState, setPreviewState] = useState<LinkPreviewState>("idle");
  const [previewResult, setPreviewResult] = useState<WishlistLinkPreview | null>(null);

  async function previewLink(url: string) {
    if (!url.trim()) return;
    setPreviewState("loading");
    setPreviewResult(null);
    try {
      const result: WishlistLinkPreview = await api.wishlistLinkPreview(homeId, url.trim());
      // Retrieved metadata is genuinely applied to the item's own fields
      // here — never overwriting something the user already typed — the
      // preview block below is additive confirmation of that, not a
      // replacement for actually populating the form.
      if (!name.trim() && result.title) setName(result.title);
      if (!imageUrl.trim() && result.image_url) setImageUrl(result.image_url);
      if (!price.trim() && result.price) setPrice(result.price);
      if (!currency.trim() && result.currency) setCurrency(result.currency);

      const foundSomething = Boolean(result.title || result.image_url || result.price || result.description);
      if (foundSomething) {
        setPreviewResult(result);
        setPreviewState("found");
      } else {
        setPreviewState("empty");
      }
    } catch {
      setPreviewState("error");
    }
  }

  return { previewState, previewResult, previewLink };
}

function LinkPreviewField({
  url,
  onUrlChange,
  imageUrl,
  previewState,
  previewResult,
  onFindDetails,
}: {
  url: string;
  onUrlChange: (value: string) => void;
  imageUrl: string;
  previewState: LinkPreviewState;
  previewResult: WishlistLinkPreview | null;
  onFindDetails: () => void;
}) {
  return (
    <div className="wishlists-link-field">
      <FormField label="Link (optional)">
        {(control) => <input {...control} value={url} onChange={(event) => onUrlChange(event.target.value)} maxLength={2000} placeholder="https://…" />}
      </FormField>
      <button
        type="button"
        className="secondary wishlists-preview-button"
        onClick={onFindDetails}
        disabled={previewState === "loading" || !url.trim()}
      >
        {previewState === "loading" ? "Finding preview…" : "Find product details"}
      </button>
      {previewState === "found" && previewResult && (
        <div className="wishlists-preview-result">
          <p className="wishlists-preview-result-heading">Product details found</p>
          <div className="wishlists-preview-line">
            <WishlistImage src={previewResult.image_url} alt="" />
            <span className="wishlists-preview-result-copy">
              {previewResult.title && <strong>{previewResult.title}</strong>}
              {previewResult.price && (
                <span className="quiet-state">{formatPrice(previewResult.price, previewResult.currency)}</span>
              )}
            </span>
          </div>
        </div>
      )}
      {previewState === "empty" && (
        <p className="muted">We couldn't find product details for this link. You can still add the item manually.</p>
      )}
      {previewState === "error" && <p className="muted">Preview unavailable; you can still save this item.</p>}
      {/* An image already on this item (e.g. from a prior save, on the Edit
          sheet) that the current previewState "found" block above isn't
          already showing — keeps that feedback without duplicating it. */}
      {previewState !== "found" && imageUrl && (
        <p className="wishlists-preview-line">
          <WishlistImage src={imageUrl} alt="" /> Image ready
        </p>
      )}
    </div>
  );
}

const ITEM_FIELD_MESSAGES: FormFieldMessages = {
  name: { missing: "Give this item a name.", blank: "Give this item a name." },
};

/** The item fields shared by Add item and Edit item; each sheet keeps its
 * own state, payload and save. */
function WishlistItemFields({
  homeId,
  name,
  setName,
  url,
  setUrl,
  price,
  setPrice,
  currency,
  setCurrency,
  imageUrl,
  setImageUrl,
  note,
  setNote,
  quantity,
  setQuantity,
  errors,
  onEdit,
  autoFocusName = false,
}: {
  homeId: string;
  name: string;
  setName: (value: string) => void;
  url: string;
  setUrl: (value: string) => void;
  price: string;
  setPrice: (value: string) => void;
  currency: string;
  setCurrency: (value: string) => void;
  imageUrl: string;
  setImageUrl: (value: string) => void;
  note: string;
  setNote: (value: string) => void;
  quantity: number;
  setQuantity: (value: number) => void;
  errors: FormFieldErrors;
  onEdit: (field: string) => void;
  autoFocusName?: boolean;
}) {
  const { previewState, previewResult, previewLink } = useLinkPreview({
    homeId,
    name,
    setName,
    imageUrl,
    setImageUrl,
    price,
    setPrice,
    currency,
    setCurrency,
  });
  return (
    <>
      <FormField label="Item name" error={errors.name}>
        {(control) => (
          <input
            {...control}
            name="name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              onEdit("name");
            }}
            maxLength={200}
            autoFocus={autoFocusName}
            required
          />
        )}
      </FormField>
      <LinkPreviewField
        url={url}
        onUrlChange={setUrl}
        imageUrl={imageUrl}
        previewState={previewState}
        previewResult={previewResult}
        onFindDetails={() => void previewLink(url)}
      />
      <FormRow columns={3}>
        <FormField label="Price (optional)">
          {(control) => <input {...control} value={price} onChange={(event) => setPrice(event.target.value)} placeholder="e.g. 29.99" />}
        </FormField>
        <FormField label="Currency">
          {(control) => <input {...control} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} maxLength={3} placeholder="GBP" />}
        </FormField>
        <FormField label="Quantity">
          {(control) => (
            <input
              {...control}
              type="number"
              min={1}
              value={quantity}
              onChange={(event) => setQuantity(Math.max(1, Number(event.target.value) || 1))}
            />
          )}
        </FormField>
      </FormRow>
      <FormField label="Note (optional)">
        {(control) => <input {...control} value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} />}
      </FormField>
    </>
  );
}

function WishlistSharingLabel({ detail }: { detail: WishlistOwnerDetail }) {
  if (detail.home_visible && detail.share_count > 0) {
    return `Shared with Home + ${detail.share_count} ${detail.share_count === 1 ? "person" : "people"}`;
  }
  if (detail.home_visible) return "Shared with Home";
  if (detail.share_count > 0) {
    return `Shared with ${detail.share_count} ${detail.share_count === 1 ? "person" : "people"}`;
  }
  return "Private";
}

export default function WishlistDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const router = useRouter();
  const { id: wishlistId } = use(params);
  const { activeHomeId } = useActiveHome();
  const [me, setMe] = useState<User | null>(null);
  const [detail, setDetail] = useState<WishlistDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");
  const [showActions, setShowActions] = useState(false);
  const [editing, setEditing] = useState(false);
  const [addingItem, setAddingItem] = useState(false);
  const [editingItem, setEditingItem] = useState<WishlistItemOwner | null>(null);
  const [sharing, setSharing] = useState(false);
  const [managingShares, setManagingShares] = useState(false);

  async function load() {
    try {
      const result = await api.wishlistTopLevel(wishlistId);
      setDetail(result);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
      else setError(loadErrorMessage(cause, "Could not load this wishlist."));
    }
  }

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
    void load();
  }, [wishlistId]);

  async function act(action: () => Promise<void>, fallback: string) {
    try {
      await action();
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : fallback);
    }
  }

  async function reserve(item: WishlistItemViewer) {
    await act(async () => {
      const updated = await api.reserveWishlistItem(wishlistId, item.id);
      applyItemUpdate(updated);
    }, "Could not reserve that item.");
  }

  async function markBought(item: WishlistItemViewer) {
    await act(async () => {
      const updated = await api.markWishlistItemBought(wishlistId, item.id);
      applyItemUpdate(updated);
    }, "Could not mark that item as bought.");
  }

  async function release(item: WishlistItemViewer) {
    await act(async () => {
      const updated = await api.releaseWishlistItem(wishlistId, item.id);
      applyItemUpdate(updated);
    }, "Could not release that item.");
  }

  function applyItemUpdate(updated: WishlistItemViewer) {
    setDetail((current) => {
      if (!current || !("owner_display_name" in current)) return current;
      return {
        ...current,
        items: current.items.map((row) => (row.id === updated.id ? updated : row)),
      };
    });
  }

  if (notFound) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <Link className="tertiary" href="/wish-lists">
            <ChevronLeft size={16} aria-hidden="true" /> Wishlists
          </Link>
          <p className="empty-mini">That wishlist could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!me || !detail) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading wishlist…</p>
        </main>
      </AppShellContent>
    );
  }

  const owner = isOwnerDetail(detail, me.id);
  const Glyph = occasionGlyph(detail.occasion);

  return (
    <AppShellContent>
      <main className="standard-page wishlists-detail-page">
        <Link className="tertiary wishlists-back-link" href="/wish-lists">
          <ChevronLeft size={16} aria-hidden="true" /> Wishlists
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              <Glyph size={14} aria-hidden="true" /> {occasionLabel(detail.occasion)}
            </p>
            <h1>{detail.title}</h1>
            {!owner && (
              <p className="quiet-state">{detail.owner_display_name}'s wishlist</p>
            )}
          </div>
          {owner && (
            <button
              type="button"
              className="icon-button secondary"
              aria-label="Wishlist actions"
              onClick={() => setShowActions(true)}
            >
              <MoreVertical size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        {detail.description && <p className="muted">{detail.description}</p>}
        {owner && (
          <button type="button" className="wishlists-visibility-indicator secondary" onClick={() => setSharing(true)}>
            {detail.home_visible ? <Users size={15} aria-hidden="true" /> : <LockKeyhole size={15} aria-hidden="true" />}
            <span>{WishlistSharingLabel({ detail })}</span>
          </button>
        )}
        <FormStatus error={error} />

        {owner && (
          <div className="wishlists-toolbar">
            <button type="button" onClick={() => setAddingItem(true)}>
              <Plus size={16} aria-hidden="true" /> Add item
            </button>
            <button type="button" className="secondary" onClick={() => setSharing(true)}>
              <Share2 size={16} aria-hidden="true" /> Share wishlist
            </button>
          </div>
        )}

        {detail.items.length === 0 ? (
          <p className="empty-mini">
            {owner ? "Add the first item to this wishlist." : "This wishlist has no items yet."}
          </p>
        ) : owner ? (
          <div className="wishlists-item-list">
            {detail.items.map((item) => (
              <button
                type="button"
                className="wishlists-item-row"
                key={item.id}
                onClick={() => setEditingItem(item)}
                aria-label={`Edit ${item.name}`}
              >
                {item.image_url && <WishlistImage src={item.image_url} alt="" />}
                <span className="wishlists-item-copy">
                  <strong>{item.name}</strong>
                  <span className="quiet-state">
                    {[
                      item.quantity > 1 ? `Qty ${item.quantity}` : null,
                      formatPrice(item.price, item.currency),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {item.note && <span className="wishlists-item-note">{item.note}</span>}
                  {item.url && <span className="wishlists-item-domain">{domainFor(item.url)}</span>}
                </span>
                <ExternalLink size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        ) : (
          <div className="wishlists-item-list">
            {detail.items.map((item) => (
              <div className="wishlists-item-row wishlists-item-row-viewer" key={item.id}>
                {item.image_url && <WishlistImage src={item.image_url} alt="" />}
                <span className="wishlists-item-copy">
                  <strong>{item.name}</strong>
                  <span className="quiet-state">
                    {[
                      item.quantity > 1 ? `Qty ${item.quantity}` : null,
                      formatPrice(item.price, item.currency),
                      item.note,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {item.url && (
                    <a
                      className="wishlists-item-link"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(event) => {
                        // Inside the Capacitor shell, taking over the main
                        // authenticated WebView with an arbitrary external
                        // product link isn't safe — route it through the
                        // system browser instead. In an ordinary browser
                        // tab, the anchor's own target="_blank" already
                        // does the right thing, so this is a no-op there.
                        event.preventDefault();
                        void openExternalUrl(item.url!);
                      }}
                    >
                      <ExternalLink size={14} aria-hidden="true" /> View item
                    </a>
                  )}
                  <span className={`wishlists-status wishlists-status-${item.reservation_status}`}>
                    {item.reservation_status === "available" && "Available"}
                    {item.reservation_status === "reserved" && "Reserved"}
                    {item.reservation_status === "bought" && "Bought"}
                    {item.reservation_status !== "available" &&
                      item.reserved_by_display_name &&
                      ` by ${item.reserved_by_display_name}`}
                  </span>
                </span>
                <span className="wishlists-item-actions">
                  {item.reservation_status === "available" ? (
                    <>
                    <button type="button" className="secondary" onClick={() => void reserve(item)}>
                        Reserve
                      </button>
                      <button type="button" className="secondary" onClick={() => void markBought(item)}>
                        Mark as bought
                      </button>
                    </>
                  ) : (
                    <button type="button" className="secondary" onClick={() => void release(item)}>
                      Release
                    </button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}

        {owner && showActions && (
          <BottomSheet title="Wishlist actions" onDismiss={() => setShowActions(false)}>
            <div className="meal-actions-sheet">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setEditing(true);
                  setShowActions(false);
                }}
              >
                Edit wishlist
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setManagingShares(true);
                  setShowActions(false);
                }}
              >
                Manage sharing
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  void act(async () => {
                    if (!activeHomeId) return;
                    if (!window.confirm(`Delete "${detail.title}"? This will remove the wishlist and its items.`))
                      return;
                    await api.deleteWishlist(activeHomeId, wishlistId);
                    router.push("/wish-lists");
                  }, "Could not delete this wishlist.")
                }
              >
                <Trash2 size={16} aria-hidden="true" /> Delete wishlist
              </button>
            </div>
          </BottomSheet>
        )}

        {owner && activeHomeId && editing && (
          <EditWishlistSheet
            homeId={activeHomeId}
            detail={detail}
            onClose={() => setEditing(false)}
            onSaved={(updated) => {
              setDetail(updated);
              setEditing(false);
            }}
          />
        )}

        {owner && activeHomeId && addingItem && (
          <AddItemSheet
            homeId={activeHomeId}
            wishlistId={wishlistId}
            onClose={() => setAddingItem(false)}
            onSaved={(updated) => {
              setDetail(updated);
              setAddingItem(false);
            }}
          />
        )}

        {owner && activeHomeId && editingItem && (
          <EditItemSheet
            homeId={activeHomeId}
            wishlistId={wishlistId}
            item={editingItem}
            onClose={() => setEditingItem(null)}
            onSaved={(updated) => {
              setDetail(updated);
              setEditingItem(null);
            }}
            onDeleted={(updated) => {
              setDetail(updated);
              setEditingItem(null);
            }}
          />
        )}

        {owner && activeHomeId && sharing && (
          <ShareWishlistSheet
            homeId={activeHomeId}
            wishlistId={wishlistId}
            detail={detail}
            onClose={() => setSharing(false)}
            onUpdated={(updated) => setDetail(updated)}
            onManagePeople={() => {
              setSharing(false);
              setManagingShares(true);
            }}
          />
        )}

        {owner && activeHomeId && managingShares && (
          <ManageSharesSheet
            homeId={activeHomeId}
            wishlistId={wishlistId}
            onClose={() => setManagingShares(false)}
          />
        )}
      </main>
    </AppShellContent>
  );
}

function EditWishlistSheet({
  homeId,
  detail,
  onClose,
  onSaved,
}: {
  homeId: string;
  detail: WishlistOwnerDetail;
  onClose: () => void;
  onSaved: (detail: WishlistOwnerDetail) => void;
}) {
  const [values, setValues] = useState<WishlistFieldValues>({
    title: detail.title,
    occasion: detail.occasion,
    occasionDate: detail.occasion_date ?? "",
    description: detail.description ?? "",
  });
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
      const payload: WishlistUpdatePayload = {
        title: values.title.trim(),
        occasion: values.occasion,
        occasion_date: values.occasionDate || null,
        description: values.description.trim() || null,
        expected_updated_at: detail.updated_at,
      };
      const updated = await api.updateWishlist(homeId, detail.id, payload);
      onSaved(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this wishlist.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormSheet
      title="Edit wishlist"
      onDismiss={onClose}
      busy={busy}
      primaryAction={
        <button type="submit" form="wishlist-edit-form" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      }
    >
      <FormLayout id="wishlist-edit-form" ref={fields.formRef} onSubmit={submit}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <WishlistFields
          values={values}
          errors={fields.errors}
          onChange={(patch, field) => {
            setValues((current) => ({ ...current, ...patch }));
            fields.clear(field);
          }}
        />
      </FormLayout>
    </FormSheet>
  );
}

function AddItemSheet({
  homeId,
  wishlistId,
  onClose,
  onSaved,
}: {
  homeId: string;
  wishlistId: string;
  onClose: () => void;
  onSaved: (detail: WishlistOwnerDetail) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [note, setNote] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = useFormFieldErrors(ITEM_FIELD_MESSAGES);

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
      const payload: WishlistItemCreatePayload = {
        name: name.trim(),
        url: url.trim() || null,
        price: price.trim() || null,
        currency: currency.trim() || null,
        note: note.trim() || null,
        image_url: imageUrl.trim() || null,
        quantity,
      };
      const updated = await api.addWishlistItem(homeId, wishlistId, payload);
      onSaved(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add that item.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormSheet
      title="Add item"
      onDismiss={onClose}
      busy={busy}
      primaryAction={
        <button type="submit" form="wishlist-item-form" disabled={busy}>
          {busy ? "Adding…" : "Add item"}
        </button>
      }
    >
      <FormLayout id="wishlist-item-form" className="wishlists-item-form" ref={fields.formRef} onSubmit={submit}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <WishlistItemFields
          homeId={homeId}
          name={name}
          setName={setName}
          url={url}
          setUrl={setUrl}
          price={price}
          setPrice={setPrice}
          currency={currency}
          setCurrency={setCurrency}
          imageUrl={imageUrl}
          setImageUrl={setImageUrl}
          note={note}
          setNote={setNote}
          quantity={quantity}
          setQuantity={setQuantity}
          errors={fields.errors}
          onEdit={fields.clear}
          autoFocusName
        />
      </FormLayout>
    </FormSheet>
  );
}

function EditItemSheet({
  homeId,
  wishlistId,
  item,
  onClose,
  onSaved,
  onDeleted,
}: {
  homeId: string;
  wishlistId: string;
  item: WishlistItemOwner;
  onClose: () => void;
  onSaved: (detail: WishlistOwnerDetail) => void;
  onDeleted: (detail: WishlistOwnerDetail) => void;
}) {
  const [name, setName] = useState(item.name);
  const [url, setUrl] = useState(item.url ?? "");
  const [price, setPrice] = useState(item.price ?? "");
  const [currency, setCurrency] = useState(item.currency ?? "");
  const [imageUrl, setImageUrl] = useState(item.image_url ?? "");
  const [note, setNote] = useState(item.note ?? "");
  const [quantity, setQuantity] = useState(item.quantity);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = useFormFieldErrors(ITEM_FIELD_MESSAGES);

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
      const payload: WishlistItemUpdatePayload = {
        name: name.trim(),
        url: url.trim() || null,
        price: price.trim() || null,
        currency: currency.trim() || null,
        note: note.trim() || null,
        image_url: imageUrl.trim() || null,
        quantity,
      };
      const updated = await api.updateWishlistItem(homeId, wishlistId, item.id, payload);
      onSaved(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this item.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    try {
      const updated = await api.removeWishlistItem(homeId, wishlistId, item.id);
      onDeleted(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove this item.");
    }
  }

  return (
    <FormSheet
      title="Edit item"
      onDismiss={onClose}
      busy={busy}
      primaryAction={
        <button type="submit" form="wishlist-item-form" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      }
    >
      <FormLayout id="wishlist-item-form" className="wishlists-item-form" ref={fields.formRef} onSubmit={submit}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <WishlistItemFields
          homeId={homeId}
          name={name}
          setName={setName}
          url={url}
          setUrl={setUrl}
          price={price}
          setPrice={setPrice}
          currency={currency}
          setCurrency={setCurrency}
          imageUrl={imageUrl}
          setImageUrl={setImageUrl}
          note={note}
          setNote={setNote}
          quantity={quantity}
          setQuantity={setQuantity}
          errors={fields.errors}
          onEdit={fields.clear}
        />
        <button type="button" className="secondary" disabled={busy} onClick={() => void remove()}>
          <Trash2 size={16} aria-hidden="true" /> Remove item
        </button>
      </FormLayout>
    </FormSheet>
  );
}

function ShareWishlistSheet({
  homeId,
  wishlistId,
  detail,
  onClose,
  onUpdated,
  onManagePeople,
}: {
  homeId: string;
  wishlistId: string;
  detail: WishlistOwnerDetail;
  onClose: () => void;
  onUpdated: (detail: WishlistOwnerDetail) => void;
  onManagePeople: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [matchedUser, setMatchedUser] = useState<{ id: string; displayName: string } | null>(null);
  const [checkedEmail, setCheckedEmail] = useState(false);
  const [guestReveal, setGuestReveal] = useState<GuestShareCreateResponse | null>(null);
  const [copied, setCopied] = useState<"link" | "pin" | null>(null);
  const [homeVisible, setHomeVisible] = useState(detail.home_visible);
  const [visibilityBusy, setVisibilityBusy] = useState(false);
  const fields = useFormFieldErrors({
    name: { missing: "Add a name for whoever you're sharing with.", blank: "Add a name for whoever you're sharing with." },
  });

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
      if (email.trim() && !checkedEmail) {
        const result = await api.lookupShareRecipient(homeId, wishlistId, email.trim());
        if (result.existing_user_id && result.existing_user_display_name) {
          setMatchedUser({ id: result.existing_user_id, displayName: result.existing_user_display_name });
          setCheckedEmail(true);
          setBusy(false);
          return;
        }
        setCheckedEmail(true);
      }
      await createShare(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not share this wishlist.");
    } finally {
      setBusy(false);
    }
  }

  async function createShare(confirmMykhayaUser: boolean) {
    const payload: ShareCreatePayload = confirmMykhayaUser
      ? {
          recipient_name: name.trim(),
          recipient_email: email.trim(),
          share_type: "mykhaya_user",
          confirmed_user_id: matchedUser?.id,
        }
      : {
          recipient_name: name.trim(),
          recipient_email: email.trim() || null,
          share_type: "guest",
        };
    const result = await api.createShare(homeId, wishlistId, payload);
    if ("link_token" in result) {
      setGuestReveal(result);
    } else {
      onClose();
    }
  }

  async function toggleHomeVisibility() {
    if (visibilityBusy) return;
    setVisibilityBusy(true);
    setError("");
    try {
      const updated = await api.setWishlistHomeVisibility(homeId, wishlistId, { enabled: !homeVisible });
      setHomeVisible(updated.home_visible);
      onUpdated(updated);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not update Home sharing.");
    } finally {
      setVisibilityBusy(false);
    }
  }

  async function copy(kind: "link" | "pin", value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
    } catch {
      // Clipboard access can fail silently (permissions/older browsers) —
      // the value stays selectable on screen either way.
    }
  }

  if (guestReveal) {
    const link = `${typeof window === "undefined" ? "" : window.location.origin}/wishlist/share/${guestReveal.link_token}`;
    return (
      <BottomSheet title="Share link created" onDismiss={onClose}>
        <p className="muted">
          This link and PIN are shown once. Copy them now and share them with {guestReveal.recipient_name} —
          MyKhaya won't show them again.
        </p>
        <label>
          Link
          <input value={link} readOnly />
        </label>
        <button type="button" className="secondary" onClick={() => void copy("link", link)}>
          <Copy size={14} aria-hidden="true" /> {copied === "link" ? "Copied" : "Copy link"}
        </button>
        <label>
          PIN
          <input value={guestReveal.pin} readOnly />
        </label>
        <button type="button" className="secondary" onClick={() => void copy("pin", guestReveal.pin)}>
          <Copy size={14} aria-hidden="true" /> {copied === "pin" ? "Copied" : "Copy PIN"}
        </button>
        <button className="sheet-primary" type="button" onClick={onClose}>
          Done
        </button>
      </BottomSheet>
    );
  }

  if (matchedUser) {
    return (
      <BottomSheet title="Share wishlist" onDismiss={onClose}>
        <p>
          {matchedUser.displayName} already uses MyKhaya — share directly with their account?
        </p>
        <FormStatus error={error} />
        <button
          className="sheet-primary"
          type="button"
          disabled={busy}
          onClick={() =>
            void (async () => {
              setBusy(true);
              try {
                await createShare(true);
              } catch (cause) {
                setError(cause instanceof ApiError ? cause.message : "Could not share this wishlist.");
              } finally {
                setBusy(false);
              }
            })()
          }
        >
          Share with their account
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() =>
            void (async () => {
              setBusy(true);
              try {
                await createShare(false);
              } catch (cause) {
                setError(cause instanceof ApiError ? cause.message : "Could not share this wishlist.");
              } finally {
                setBusy(false);
              }
            })()
          }
        >
          Send a guest link instead
        </button>
      </BottomSheet>
    );
  }

  return (
    <FormSheet
      title="Share wishlist"
      onDismiss={onClose}
      busy={busy}
      primaryAction={
        <button type="submit" form="wishlist-share-form" disabled={busy}>
          {busy ? "Sharing…" : "Share wishlist"}
        </button>
      }
    >
      <section className="wishlists-share-section">
        <div className="wishlists-share-toggle-copy">
          <strong>Share with your Home</strong>
          <p className="muted">Everyone in this Home with Wishlists access can view and shop this list. Your own reservation details stay private.</p>
        </div>
        <button type="button" className={`toggle ${homeVisible ? "is-on" : ""}`} role="switch" aria-checked={homeVisible} onClick={() => void toggleHomeVisibility()} disabled={visibilityBusy}>
          <span>{homeVisible ? "On" : "Off"}</span>
        </button>
      </section>
      <button type="button" className="secondary" onClick={onManagePeople}>
        Manage people ({detail.share_count})
      </button>
      <FormLayout id="wishlist-share-form" className="wishlists-share-form" ref={fields.formRef} onSubmit={submit}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Name" error={fields.errors.name}>
          {(control) => (
            <input
              {...control}
              name="name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                fields.clear("name");
              }}
              maxLength={100}
              autoFocus
              required
            />
          )}
        </FormField>
        <FormField label="Email (optional — checks for a MyKhaya account)" error={fields.errors.email}>
          {(control) => (
            <input
              {...control}
              name="email"
              type="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setCheckedEmail(false);
                fields.clear("email");
              }}
            />
          )}
        </FormField>
      </FormLayout>
    </FormSheet>
  );
}

function ManageSharesSheet({
  homeId,
  wishlistId,
  onClose,
}: {
  homeId: string;
  wishlistId: string;
  onClose: () => void;
}) {
  const [shares, setShares] = useState<ShareListItem[] | null>(null);
  const [error, setError] = useState("");
  const [reveal, setReveal] = useState<GuestShareCreateResponse | null>(null);

  async function load() {
    try {
      const result = await api.shares(homeId, wishlistId);
      setShares(result.items);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load sharing.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function revoke(share: ShareListItem) {
    try {
      await api.revokeShare(homeId, wishlistId, share.id);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not revoke access.");
    }
  }

  async function regenerate(share: ShareListItem) {
    try {
      const result = await api.regenerateGuestShare(homeId, wishlistId, share.id);
      setReveal(result);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not generate a new PIN.");
    }
  }

  if (reveal) {
    return (
      <BottomSheet title="New PIN created" onDismiss={onClose}>
        <p className="muted">
          This link and PIN are shown once — copy them now for {reveal.recipient_name}.
        </p>
        <label>
          Link
          <input
            readOnly
            value={`${typeof window === "undefined" ? "" : window.location.origin}/wishlist/share/${reveal.link_token}`}
          />
        </label>
        <label>
          PIN
          <input readOnly value={reveal.pin} />
        </label>
        <button className="sheet-primary" type="button" onClick={onClose}>
          Done
        </button>
      </BottomSheet>
    );
  }

  return (
    <BottomSheet title="Manage sharing" onDismiss={onClose}>
      <FormStatus error={error} />
      {shares === null ? (
        <p role="status">Loading…</p>
      ) : shares.length === 0 ? (
        <p className="empty-mini">Not shared with anyone yet.</p>
      ) : (
        <div className="wishlists-share-list">
          {shares.map((share) => (
            <div className="wishlists-share-row" key={share.id}>
              <span className="wishlists-share-copy">
                <strong>{share.recipient_name}</strong>
                <span className="quiet-state">
                  {share.share_type === "guest" ? "Guest link" : "MyKhaya account"}
                  {share.revoked ? " · Revoked" : ""}
                </span>
              </span>
              {!share.revoked && (
                <span className="wishlists-share-actions">
                  {share.share_type === "guest" && (
                    <button type="button" className="secondary" onClick={() => void regenerate(share)}>
                      Generate new PIN
                    </button>
                  )}
                  <button type="button" className="secondary" onClick={() => void revoke(share)}>
                    Revoke access
                  </button>
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </BottomSheet>
  );
}
