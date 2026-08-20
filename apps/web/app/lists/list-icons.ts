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
