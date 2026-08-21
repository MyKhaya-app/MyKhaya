"use client";

import { FormEvent, use, useState } from "react";
import { Gift } from "lucide-react";
import type { WishlistItemViewer, WishlistViewerDetail } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { occasionGlyph, occasionLabel } from "@/app/wish-lists/occasion";

// A guest reaching this page has no MyKhaya account and no normal session —
// it deliberately never imports AppShell, useActiveHome, or anything else
// that assumes a signed-in member. Verifying the link+PIN establishes a
// separate, lightweight cookie session (mk_wishlist_guest /
// mk_wishlist_guest_csrf — see wishlist_guest.py), never the normal
// mk_session/mk_csrf pair. See docs/product/wishlists.md.

function formatPrice(price: string | null, currency: string | null): string | null {
  if (!price) return null;
  return currency ? `${currency} ${price}` : price;
}

export default function GuestWishlistSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [recipientName, setRecipientName] = useState<string | null>(null);
  const [detail, setDetail] = useState<WishlistViewerDetail | null>(null);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.verifyGuestShare(token, pin.trim());
      setRecipientName(result.recipient_name);
      const wishlist = await api.guestWishlist();
      setDetail(wishlist);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("That link or PIN is invalid.");
      } else if (cause instanceof ApiError && cause.status === 429) {
        setError("Too many attempts — please wait a few minutes and try again.");
      } else {
        setError(cause instanceof ApiError ? cause.message : "Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    try {
      const wishlist = await api.guestWishlist();
      setDetail(wishlist);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not refresh this wishlist.");
    }
  }

  async function reserve(item: WishlistItemViewer) {
    try {
      await api.guestReserveItem(item.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not reserve that item.");
    }
  }

  async function markBought(item: WishlistItemViewer) {
    try {
      await api.guestMarkItemBought(item.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not mark that item as bought.");
    }
  }

  async function release(item: WishlistItemViewer) {
    try {
      await api.guestReleaseItem(item.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not release that item.");
    }
  }

  if (!detail) {
    return (
      <main className="guest-wishlist-page">
        <div className="card guest-wishlist-verify">
          <p className="eyebrow">
            <Gift size={14} aria-hidden="true" /> Wishlist
          </p>
          <h1>Enter the PIN to view this wishlist</h1>
          <p className="muted">Ask whoever shared this link for the 6-digit PIN.</p>
          <form onSubmit={verify}>
            <label>
              PIN
              <input
                inputMode="numeric"
                value={pin}
                onChange={(event) => setPin(event.target.value)}
                maxLength={6}
                autoFocus
                required
              />
            </label>
            <FormStatus error={error} />
            <button className="sheet-primary" disabled={busy || !pin.trim()}>
              {busy ? "Checking…" : "View wishlist"}
            </button>
          </form>
        </div>
      </main>
    );
  }

  const Glyph = occasionGlyph(detail.occasion);

  return (
    <main className="guest-wishlist-page">
      <div className="guest-wishlist-heading">
        <p className="eyebrow">
          <Glyph size={14} aria-hidden="true" /> {occasionLabel(detail.occasion)}
        </p>
        <h1>{detail.title}</h1>
        <p className="quiet-state">{detail.owner_display_name}'s wishlist{recipientName ? ` · Viewing as ${recipientName}` : ""}</p>
        {detail.description && <p className="muted">{detail.description}</p>}
      </div>
      <FormStatus error={error} />

      {detail.items.length === 0 ? (
        <p className="empty-mini">This wishlist has no items yet.</p>
      ) : (
        <div className="wishlists-item-list">
          {detail.items.map((item) => (
            <div className="wishlists-item-row wishlists-item-row-viewer" key={item.id}>
              <span className="wishlists-item-copy">
                <strong>{item.name}</strong>
                <span className="quiet-state">
                  {[item.quantity > 1 ? `Qty ${item.quantity}` : null, formatPrice(item.price, item.currency), item.note]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {item.url && (
                  <a className="wishlists-item-link" href={item.url} target="_blank" rel="noreferrer">
                    View item
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
    </main>
  );
}
