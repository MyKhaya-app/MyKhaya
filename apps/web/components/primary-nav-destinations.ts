import type { PrincipalType } from "@mykhaya/shared-types";

// The single source of truth for MyKhaya's primary app-level destinations —
// currently consumed by BottomNav (bottom-nav.tsx). Deliberately NOT placed
// in @mykhaya/shared-types: that package is generated from the backend's
// OpenAPI schema (see its header comment) and would be silently overwritten
// by the next `make generate-client` run — navigation structure isn't an
// API concept.
//
// This also anchors the "which nav changes need a new iOS release vs which
// stay server-deployed" answer for the future native tab bar (task
// §11/ADR 0012): the *set* of destinations below (id, path, adult-only
// gating) is exactly what a native Swift tab bar would need to hardcode as
// its own tabs, so a genuinely new/removed/reordered destination needs a
// native release; anything else about a destination's own page is an
// ordinary web deploy, same as today.
export interface PrimaryNavDestination {
  id: "home" | "calendar" | "family" | "more";
  href: string;
  label: string;
  adultOnly: boolean;
}

export const PRIMARY_NAV_DESTINATIONS: readonly PrimaryNavDestination[] = [
  { id: "home", href: "/home", label: "Home", adultOnly: false },
  { id: "calendar", href: "/calendar", label: "Calendar", adultOnly: false },
  // "Family" is primarily invitation and membership management — not part
  // of a Child's restricted surface.
  { id: "family", href: "/people", label: "Family", adultOnly: true },
  { id: "more", href: "/settings", label: "More", adultOnly: false },
];

export function primaryNavDestinationsFor(
  principalType?: PrincipalType,
): readonly PrimaryNavDestination[] {
  return PRIMARY_NAV_DESTINATIONS.filter(
    (item) => !item.adultOnly || principalType !== "managed_child",
  );
}
