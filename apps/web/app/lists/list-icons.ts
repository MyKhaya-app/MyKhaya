import {
  GraduationCap,
  Home as HomeIcon,
  ListChecks,
  Luggage,
  PartyPopper,
  ShoppingBasket,
  ShoppingCart,
  TreePine,
} from "lucide-react";
import type { ListIcon } from "@mykhaya/shared-types";

export const LIST_ICON_OPTIONS: { key: ListIcon; label: string }[] = [
  { key: "groceries", label: "Groceries" },
  { key: "shopping", label: "Shopping" },
  { key: "packing", label: "Packing" },
  { key: "home", label: "Home" },
  { key: "school", label: "School" },
  { key: "party", label: "Party" },
  { key: "christmas", label: "Christmas" },
  { key: "other", label: "Other" },
];

// Presentation-only artwork for the Lists overview cards (see
// apps/web/public/images/lists-*.png). ListIcon is a fixed 8-value preset
// mirroring the backend's mykhaya.schemas.LIST_ICONS — there is no
// per-list custom/arbitrary category, so every real list maps to exactly
// one of these keys (or none, via the `| null` fallback).
//
// apps/web/public/images/ also holds lists-pet-supplies.png,
// lists-wish-list.png, lists-car.png, lists-diy.png, lists-fitness.png,
// lists-health.png and lists-recipes.png, none of which are referenced
// below. These are kept deliberately, reserved for future MyKhaya
// ListIcon presets (pets/wishlist/car/DIY/fitness/health/recipes) should
// the backend enum ever grow — not selectable today, and not wired to any
// current list. Do not repurpose one of these images for an existing key
// above; add the real enum value first (a backend schema change, out of
// scope for this presentation layer).
export function listIconImage(icon: ListIcon | null): string {
  switch (icon) {
    case "groceries":
      return "/images/lists-groceries.png";
    case "shopping":
      return "/images/lists-shopping.png";
    case "packing":
      return "/images/lists-travel.png";
    case "home":
      return "/images/lists-household.png";
    case "school":
      return "/images/lists-school.png";
    case "party":
      return "/images/lists-events.png";
    case "christmas":
      return "/images/lists-gifts.png";
    default:
      return "/images/lists-other.png";
  }
}

export function listIconGlyph(icon: ListIcon | null) {
  switch (icon) {
    case "groceries":
      return ShoppingCart;
    case "shopping":
      return ShoppingBasket;
    case "packing":
      return Luggage;
    case "home":
      return HomeIcon;
    case "school":
      return GraduationCap;
    case "party":
      return PartyPopper;
    case "christmas":
      return TreePine;
    default:
      return ListChecks;
  }
}
