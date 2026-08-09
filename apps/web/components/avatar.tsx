"use client";

import { useState } from "react";
import { memberColours } from "@mykhaya/design-tokens";

// Identity belongs to a person, not an event category — every family
// member gets one colour, used everywhere they appear (avatar, their
// events on Calendar, their items on any future per-person list). Colour
// is always decorative on top of initials, never the only signal of
// identity. See docs/design/visual-identity.md.
//
// The real, persisted colour lives on Membership (assigned server-side,
// collision-free within a home) and should be passed in via the `colour`
// prop whenever a full Member record is available. The hash below is only
// a fallback for the rare case there's no persisted colour yet (a
// membership created before this field existed) or only a bare user id is
// on hand.

function hashPalette(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return memberColours[hash % memberColours.length]!;
}

function contrastText(hex: string): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) return "#FFFEFB";
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  // Relative luminance (sRGB, unlinearised approximation — good enough for
  // picking readable text on a solid fill, not a WCAG-precise calculation).
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? "#233028" : "#FFFEFB";
}

/** The colour Avatar renders for this person: the real persisted colour
 *  when known, otherwise the deterministic fallback hash. Use this
 *  wherever something other than the avatar itself (an event marker, a
 *  dot) needs to read as "belongs to them". */
export function memberColour(id: string, persisted?: string | null): string {
  return persisted ?? hashPalette(id);
}

const SIZES = { sm: 32, md: 44, lg: 56, xl: 72 } as const;

/** `avatar_version` is a fresh, unpredictable filename stem generated server-side on
 *  every upload (see mykhaya/avatars/) — using it as the cache-busting query param
 *  means a changed avatar always invalidates any cached copy of the old URL, while
 *  the image itself is served with a long, immutable Cache-Control. */
export function avatarUrl(id: string, version: string): string {
  return `/api/v1/users/${encodeURIComponent(id)}/avatar?v=${encodeURIComponent(version)}`;
}

export function Avatar({
  id,
  name,
  colour,
  avatarVersion,
  size = "md",
}: {
  id: string;
  name: string;
  /** The real persisted Membership.colour, when a full Member record is
   *  available. Falls back to the deterministic hash when omitted/null. */
  colour?: string | null;
  /** User.avatar_version / Member.avatar_version — null/undefined means no custom
   *  avatar, so the initials below are shown as-is. */
  avatarVersion?: string | null;
  size?: keyof typeof SIZES;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const bg = memberColour(id, colour);
  const text = contrastText(bg);
  const px = SIZES[size];
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const showImage = Boolean(avatarVersion) && !imageFailed;
  return (
    <span
      className={`avatar avatar-${size}`}
      style={{ width: px, height: px, background: bg, color: text }}
      aria-hidden="true"
    >
      {showImage ? (
        <img
          src={avatarUrl(id, avatarVersion!)}
          alt=""
          width={px}
          height={px}
          onError={() => setImageFailed(true)}
        />
      ) : (
        initial
      )}
    </span>
  );
}
