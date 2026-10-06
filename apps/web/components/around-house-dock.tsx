"use client";

import Link from "next/link";
import {
  CalendarPlus,
  Car,
  ClipboardList,
  Gift,
  House,
  ListChecks,
  Lock,
  UserPlus,
  UtensilsCrossed,
  WalletCards,
} from "lucide-react";
import { canAddMember } from "./member-entitlement-logic";
import { featureEnabled, useHomeAccess } from "./home-access";
import { useActiveHome } from "./use-active-home";

function QuickAction({
  href,
  label,
  icon,
  locked = false,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  locked?: boolean;
}) {
  return (
    <Link className={`around-house-dock-action${locked ? " quick-action-locked" : ""}`} href={href}>
      {locked && (
        <span className="quick-action-lock" aria-hidden="true">
          <Lock size={11} />
        </span>
      )}
      {icon}
      {label}
    </Link>
  );
}

export function AroundHouseDock() {
  const { activeHome } = useActiveHome();
  const { access } = useHomeAccess();
  const canInviteFamily = activeHome?.capabilities.includes("members.invite") ?? false;

  // Unresolved or failed Home/feature state renders nothing: the dock never
  // shows dead shortcuts while the current Home's access loads. (It floats
  // above the page, so an absent dock reserves no layout.)
  if (!activeHome || access.state !== "ready") return null;
  const { billing, features: matrix } = access.value;
  const dockState = {
    calendar: featureEnabled(matrix, "calendar"),
    inviteFamily: canAddMember(billing.member_usage) && canInviteFamily,
    nudges: { released: featureEnabled(matrix, "nudges"), entitled: billing.nudges_enabled },
    meals: { released: featureEnabled(matrix, "meals"), entitled: billing.meals_enabled },
    lists: { released: featureEnabled(matrix, "shopping"), entitled: billing.lists_enabled },
    wishlists: { released: featureEnabled(matrix, "wish_lists"), entitled: billing.wishlists_enabled },
    driveway: billing.driveway_enabled,
    budget: billing.budget_enabled,
  };

  const actions = [
    dockState.calendar && (
      <QuickAction
        key="calendar"
        href="/calendar"
        label="Add event"
        icon={<CalendarPlus size={19} aria-hidden="true" />}
      />
    ),
    dockState.inviteFamily && (
      <QuickAction
        key="invite"
        href="/settings/members"
        label="Invite family"
        icon={<UserPlus size={19} aria-hidden="true" />}
      />
    ),
    dockState.nudges.released && (
      <QuickAction
        key="nudges"
        href="/settings/routines-reminders"
        label="Nudges"
        locked={!dockState.nudges.entitled}
        icon={<ClipboardList size={19} aria-hidden="true" />}
      />
    ),
    dockState.meals.released && (
      <QuickAction
        key="meals"
        href="/meal-plans"
        label="Meal plans"
        locked={!dockState.meals.entitled}
        icon={<UtensilsCrossed size={19} aria-hidden="true" />}
      />
    ),
    dockState.lists.released && (
      <QuickAction
        key="lists"
        href="/lists"
        label="Lists"
        locked={!dockState.lists.entitled}
        icon={<ListChecks size={19} aria-hidden="true" />}
      />
    ),
    dockState.wishlists.released && (
      <QuickAction
        key="wishlists"
        href="/wish-lists"
        label="Wishlists"
        locked={!dockState.wishlists.entitled}
        icon={<Gift size={19} aria-hidden="true" />}
      />
    ),
    dockState.driveway && (
      <QuickAction
        key="driveway"
        href="/driveway"
        label="Driveway"
        icon={<Car size={19} aria-hidden="true" />}
      />
    ),
    dockState.budget && (
      <QuickAction
        key="budget"
        href="/budget"
        label="Budget"
        icon={<WalletCards size={19} aria-hidden="true" />}
      />
    ),
  ].filter(Boolean);

  if (actions.length === 0) return null;

  return (
    <aside className="around-house-dock" aria-label="Around the house">
      <div className="around-house-dock-heading">
        <span className="around-house-dock-icon" aria-hidden="true">
          <House size={18} />
        </span>
        <h2>Around the house</h2>
      </div>
      <nav className="around-house-dock-actions" aria-label="Household shortcuts">
        {actions}
      </nav>
    </aside>
  );
}
