import { Cake, Gift, PartyPopper, Sparkles } from "lucide-react";
import type { WishlistOccasion } from "@mykhaya/shared-types";

// Small shared vocabulary for occasion display — mirrors list-icons.ts's
// shape for Lists' icon picker.
export const WISHLIST_OCCASION_OPTIONS: { key: WishlistOccasion; label: string }[] = [
  { key: "birthday", label: "Birthday" },
  { key: "christmas", label: "Christmas" },
  { key: "general", label: "General" },
  { key: "other", label: "Other occasion" },
];

export function occasionLabel(occasion: WishlistOccasion): string {
  return WISHLIST_OCCASION_OPTIONS.find((row) => row.key === occasion)?.label ?? "Other occasion";
}

export function occasionGlyph(occasion: WishlistOccasion) {
  switch (occasion) {
    case "birthday":
      return Cake;
    case "christmas":
      return PartyPopper;
    case "general":
      return Sparkles;
    default:
      return Gift;
  }
}
