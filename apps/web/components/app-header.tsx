"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronDown, LogOut, Settings, Shield, User as UserIcon } from "lucide-react";
import type { Home, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AccountMenu, maskEmail } from "./account-menu";
import { Logo } from "./logo";
import { Avatar } from "./avatar";
import { BottomSheet } from "./bottom-sheet";
import { HeaderBotanical } from "./header-botanical";
import { useAuth } from "./auth-provider";
import { nativeLogout } from "./native-auth";
import { isNativeShell } from "./native-runtime";
import { useDesktopShellActive } from "./use-desktop-shell";
import { NotificationBell, NotificationTray } from "./notification-tray";

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
  const { clearSession } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);
  const desktopShellActive = useDesktopShellActive();

  async function logout() {
    if (signingOut) return;
    setSigningOut(true);
    setSignOutError(null);
    try {
      // Native source of truth: revokes the Keychain-backed bearer session
      // (see components/native-auth.ts), never the browser cookie
      // /auth/logout — the two transports are never merged.
      if (isNativeShell()) {
        await nativeLogout();
      } else {
        await api.post("/auth/logout", {});
      }
      // Clears in-memory user/status so no protected route can keep
      // rendering, or be restored via browser Back, once the server
      // session is gone — see auth-provider.tsx's clearSession doc comment.
      clearSession();
      setMenuOpen(false);
      router.push("/login");
    } catch {
      // Keep the user authenticated and the menu open on failure — never
      // clear local state and pretend logout succeeded.
      setSignOutError("Sign out failed. Please try again.");
    } finally {
      setSigningOut(false);
    }
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
      <div className="app-header-actions">
        {user ? <NotificationBell onOpen={() => setNotificationsOpen(true)} /> : null}
        <button
          ref={avatarRef}
          type="button"
          className="app-header-avatar"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label="Open profile menu"
          aria-haspopup="true"
          aria-expanded={menuOpen}
        >
          <Avatar
            id={user?.id ?? "?"}
            name={user?.display_name ?? "?"}
            avatarVersion={user?.avatar_version}
            size="md"
          />
        </button>
      </div>

      {notificationsOpen && <NotificationTray onDismiss={() => setNotificationsOpen(false)} />}

      {menuOpen && desktopShellActive && (
        <AccountMenu
          anchorRef={avatarRef}
          user={user}
          onClose={() => setMenuOpen(false)}
          onSignOut={logout}
          signingOut={signingOut}
          signOutError={signOutError}
        />
      )}

      {menuOpen && !desktopShellActive && (
        <BottomSheet title="Profile" onDismiss={() => setMenuOpen(false)}>
          <p className="muted" style={{ marginTop: 0 }}>
            {user?.display_name}
            {user?.email && (
              <>
                <br />
                <small>{maskEmail(user.email)}</small>
              </>
            )}
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
            <Link href="/settings/security" className="sheet-menu-item">
              <Shield size={20} aria-hidden="true" />
              Security
            </Link>
            <button type="button" className="sheet-menu-item danger" onClick={logout} disabled={signingOut}>
              <LogOut size={20} aria-hidden="true" />
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </nav>
          {signOutError && (
            <p className="notice error" role="alert">
              {signOutError}
            </p>
          )}
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
