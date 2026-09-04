"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronDown, LogOut, Settings, User as UserIcon } from "lucide-react";
import type { Home, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { Logo } from "./logo";
import { Avatar } from "./avatar";
import { BottomSheet } from "./bottom-sheet";
import { HeaderBotanical } from "./header-botanical";
import { nativeLogout } from "./native-auth";
import { isNativeShell } from "./native-runtime";

export function AppHeader({
  user,
  homes,
  activeHome,
  onSwitchHome,
  flush = false,
}: {
  user: User | null;
  homes: Home[];
  activeHome: Home | null;
  onSwitchHome: (homeId: string) => void;
  flush?: boolean;
}) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);

  async function logout() {
    setMenuOpen(false);
    // Native source of truth: revokes the Keychain-backed bearer session
    // (see components/native-auth.ts), never the browser cookie
    // /auth/logout — the two transports are never merged.
    if (isNativeShell()) {
      await nativeLogout();
    } else {
      await api.post("/auth/logout", {});
    }
    router.push("/login");
  }

  return (
    <header className={`app-header${flush ? " app-header-flush" : ""}`}>
      <HeaderBotanical />
      <Link className="app-header-logo" href="/home" aria-label="Go to Home">
        <Logo compact />
      </Link>
      <button
        type="button"
        className="app-header-home"
        onClick={() => homes.length > 1 && setSwitcherOpen(true)}
        aria-haspopup={homes.length > 1 ? "dialog" : undefined}
      >
        <span>{activeHome?.name ?? "Your Home"}</span>
        {homes.length > 1 && <ChevronDown size={17} aria-hidden="true" />}
      </button>
      <button
        type="button"
        className="app-header-avatar"
        onClick={() => setMenuOpen(true)}
        aria-label="Open profile menu"
      >
        <Avatar
          id={user?.id ?? "?"}
          name={user?.display_name ?? "?"}
          avatarVersion={user?.avatar_version}
          size="md"
        />
      </button>

      {menuOpen && (
        <BottomSheet title="Profile" onDismiss={() => setMenuOpen(false)}>
          <p className="muted" style={{ marginTop: 0 }}>
            {user?.display_name}
          </p>
          <nav className="sheet-menu">
            <Link href="/settings/profile" className="sheet-menu-item">
              <UserIcon size={20} aria-hidden="true" />
              Profile
            </Link>
            <Link href="/settings" className="sheet-menu-item">
              <Settings size={20} aria-hidden="true" />
              Settings
            </Link>
            <button type="button" className="sheet-menu-item danger" onClick={logout}>
              <LogOut size={20} aria-hidden="true" />
              Sign out
            </button>
          </nav>
        </BottomSheet>
      )}

      {switcherOpen && (
        <BottomSheet title="Switch Home" onDismiss={() => setSwitcherOpen(false)}>
          <nav className="sheet-menu">
            {homes.map((home) => (
              <button
                key={home.id}
                type="button"
                className="sheet-menu-item"
                onClick={() => {
                  onSwitchHome(home.id);
                  setSwitcherOpen(false);
                }}
              >
                {home.name}
                {home.id === activeHome?.id && <span className="muted">Current</span>}
              </button>
            ))}
          </nav>
        </BottomSheet>
      )}
    </header>
  );
}
