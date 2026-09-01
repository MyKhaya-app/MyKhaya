"use client";

import { useEffect, useState } from "react";
import { contrastText, resolveColour } from "@mykhaya/design-tokens";
import { fetchNativeImage } from "./native-auth";
import { isNativeShell } from "./native-runtime";
import {
  type AvatarStackPerson,
  avatarStackLabel,
  buildAvatarStack,
} from "./avatar-stack-logic";

export type { AvatarStackPerson } from "./avatar-stack-logic";

// Identity belongs to a person, not an event category — every family
// member gets one colour, used everywhere they appear (avatar, their
// events on Calendar, their items on any future per-person list). Colour
// is always decorative on top of initials, never the only signal of
// identity. See docs/design/visual-identity.md.
//
// The real, persisted colour lives on Membership (a palette token, assigned
// server-side and collision-free within a home, editable by the person or a
// Home Admin) and should be passed in via the `colour` prop whenever a full
// Member record is available. resolveColour() falls back to a deterministic
// hash for the rare case there's no persisted colour yet, or only a bare
// user id is on hand.

/** The colour Avatar renders for this person: the real persisted colour
 *  when known, otherwise a deterministic fallback. Use this wherever
 *  something other than the avatar itself (an event marker, a dot) needs to
 *  read as "belongs to them". */
export function memberColour(id: string, persisted?: string | null): string {
  return resolveColour(persisted, id);
}

const SIZES = { sm: 32, md: 44, lg: 56, xl: 72 } as const;

/** `avatar_version` is a fresh, unpredictable filename stem generated server-side on
 *  every upload (see mykhaya/avatars/) — using it as the cache-busting query param
 *  means a changed avatar always invalidates any cached copy of the old URL, while
 *  the image itself is served with a long, immutable Cache-Control. */
export function avatarUrl(id: string, version: string): string {
  return `/api/v1${avatarPath(id, version)}`;
}

function avatarPath(id: string, version: string): string {
  return `/users/${encodeURIComponent(id)}/avatar?v=${encodeURIComponent(version)}`;
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
  const [nativeImageUrl, setNativeImageUrl] = useState<string | null>(null);
  const bg = memberColour(id, colour);
  const text = contrastText(bg);
  const px = SIZES[size];
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const showImage = Boolean(avatarVersion) && !imageFailed;
  useEffect(() => {
    setImageFailed(false);
    setNativeImageUrl(null);
    if (!isNativeShell() || !avatarVersion) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    void fetchNativeImage(avatarPath(id, avatarVersion))
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setNativeImageUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setImageFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id, avatarVersion]);
  const imageSrc = isNativeShell() ? nativeImageUrl : avatarVersion ? avatarUrl(id, avatarVersion) : null;
  return (
    <span
      className={`avatar avatar-${size}`}
      style={{ width: px, height: px, background: bg, color: text }}
      aria-hidden="true"
    >
      {showImage && imageSrc ? (
        <img
          src={imageSrc}
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

/** A compact overlapping avatar group for "who's involved in this" contexts
 *  (event cards, etc.) — one Avatar for a single person (byte-for-byte the
 *  same markup Avatar alone would render, so single-participant call sites
 *  see no visual change), an overlapping row of up to MAX_STACK_AVATARS for
 *  more, and a "+N" tile for the remainder. Ordering is whatever order
 *  `people` is passed in — callers own that (see home/page.tsx, which
 *  reuses GET /groups/{id}/members' existing display_name order rather than
 *  this component inventing its own).
 *
 *  Individual Avatars stay aria-hidden (as Avatar always is); the group
 *  carries one combined aria-label instead of one announcement per circle,
 *  so a screen reader hears "Alice, Bob and Charlie" once rather than three
 *  redundant "image" announcements. */
export function AvatarStack({
  people,
  size = "sm",
}: {
  people: AvatarStackPerson[];
  size?: keyof typeof SIZES;
}) {
  if (people.length === 0) return null;
  if (people.length === 1) {
    const [person] = people;
    return (
      <Avatar
        id={person!.user_id}
        name={person!.display_name}
        colour={person!.colour}
        avatarVersion={person!.avatar_version}
        size={size}
      />
    );
  }
  const { shown, extra } = buildAvatarStack(people);
  const label = avatarStackLabel(people);
  return (
    <span className="avatar-stack" role="img" aria-label={label}>
      {shown.map((person) => (
        <Avatar
          key={person.user_id}
          id={person.user_id}
          name={person.display_name}
          colour={person.colour}
          avatarVersion={person.avatar_version}
          size={size}
        />
      ))}
      {extra > 0 && (
        <span className={`avatar avatar-${size} avatar-stack-more`} aria-hidden="true">
          +{extra}
        </span>
      )}
    </span>
  );
}
