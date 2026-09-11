"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  CalendarPlus,
  ClipboardList,
  Gift,
  House,
  ListChecks,
  Lock,
  UserPlus,
  UtensilsCrossed,
} from "lucide-react";
import { api } from "@mykhaya/api-client";
import { canAddMember } from "./member-entitlement-logic";
import { useActiveHome } from "./use-active-home";

type DockState = {
  calendar: boolean;
  inviteFamily: boolean;
  nudges: { released: boolean; entitled: boolean };
  meals: { released: boolean; entitled: boolean };
  lists: { released: boolean; entitled: boolean };
  wishlists: { released: boolean; entitled: boolean };
};

function featureEnabled(features: { feature: string; enabled: boolean }[], feature: string) {
  return features.some((item) => item.feature === feature && item.enabled);
}

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
  const { activeHomeId, activeHome } = useActiveHome();
  const canInviteFamily = activeHome?.capabilities.includes("members.invite") ?? false;
  const [dockState, setDockState] = useState<DockState | null>(null);

  useEffect(() => {
    if (!activeHomeId || !activeHome) {
      setDockState(null);
      return;
    }

    let cancelled = false;
    setDockState(null);
    Promise.all([api.billingStatus(activeHomeId), api.featureMatrix(activeHomeId)])
      .then(([billing, matrix]) => {
        if (cancelled) return;
        setDockState({
          calendar: featureEnabled(matrix.features, "calendar"),
          inviteFamily: canAddMember(billing.member_usage) && canInviteFamily,
          nudges: {
            released: featureEnabled(matrix.features, "nudges"),
            entitled: billing.nudges_enabled,
          },
          meals: {
            released: featureEnabled(matrix.features, "meals"),
            entitled: billing.meals_enabled,
          },
          lists: {
            released: featureEnabled(matrix.features, "shopping"),
            entitled: billing.lists_enabled,
          },
          wishlists: {
            released: featureEnabled(matrix.features, "wish_lists"),
            entitled: billing.wishlists_enabled,
          },
        });
      })
      .catch(() => {
        if (!cancelled) setDockState(null);
      });

    return () => {
      cancelled = true;
    };
  }, [activeHomeId, canInviteFamily]);

  // Unknown Home/feature state fails closed: the shell does not render dead
  // shortcuts while the current Home is changing or its access state loads.
  if (!dockState) return null;

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
