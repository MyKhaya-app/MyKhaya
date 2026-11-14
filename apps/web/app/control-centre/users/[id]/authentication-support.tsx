"use client";

import Link from "next/link";
import { CcBadge } from "@/components/control-centre/badge";
import { CcLoadingState, CcNotice } from "@/components/control-centre/status-message";
import { Fingerprint, History, KeyRound, Link2, MonitorSmartphone, ShieldOff, Smartphone } from "lucide-react";

export type SignInProvider = "apple" | "google";

export type UserAuthenticationSummary = {
  account_lifecycle: "active" | "disabled" | "archived" | "anonymised";
  authentication_disabled: boolean;
  providers: {
    provider: SignInProvider;
    name: string;
    connected: boolean;
    connected_at: string | null;
    last_used_at: string | null;
    enabled_in_environment: boolean;
  }[];
  password: { available: boolean; changed_at: string | null };
  passkeys: { count: number; last_used_at: string | null };
  sessions: { active_sessions: number; trusted_devices: number; last_session_activity_at: string | null };
  native_apps: {
    platform: string;
    label: string;
    active_registrations: number;
    disabled_registrations: number;
    push_environments: string[];
    last_seen_at: string | null;
  }[];
  web_push_subscriptions: number;
  recent_events: {
    label: string;
    outcome: "success" | "failure" | "info";
    initiated_by: "user" | "administrator";
    occurred_at: string;
  }[];
};

function when(value: string | null, empty = "Not recorded") {
  return value
    ? new Date(value).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : empty;
}

function ProviderIcon({ provider }: { provider: SignInProvider }) {
  // Monochrome marks used only to label the provider row.
  const path =
    provider === "apple"
      ? "M15.53 3.83c.84-1.01 1.4-2.43 1.25-3.83-1.21.05-2.66.8-3.54 1.82-.78.9-1.45 2.34-1.27 3.71 1.34.1 2.71-.69 3.56-1.7zM12.15 6.9c-.95 0-2.42-1.08-3.96-1.04-2.04.03-3.91 1.18-4.96 3.01-2.12 3.68-.55 9.1 1.52 12.09 1.01 1.45 2.21 3.09 3.79 3.04 1.52-.07 2.09-.99 3.94-.99 1.83 0 2.35.99 3.96.95 1.64-.03 2.68-1.48 3.68-2.95 1.16-1.69 1.64-3.33 1.66-3.42-.04-.01-3.18-1.22-3.22-4.86-.03-3.04 2.48-4.49 2.6-4.56-1.43-2.09-3.62-2.32-4.39-2.38-2-.16-3.68 1.09-4.61 1.09z"
      : "M12.48 10.92v3.28h7.84c-.24 1.84-.85 3.19-1.79 4.13-1.15 1.15-2.93 2.4-6.05 2.4-4.83 0-8.6-3.89-8.6-8.72s3.77-8.72 8.6-8.72c2.6 0 4.51 1.03 5.91 2.35l2.31-2.31C18.75 1.44 16.13 0 12.48 0 5.87 0 .31 5.39.31 12s5.56 12 12.17 12c3.57 0 6.27-1.17 8.37-3.36 2.16-2.16 2.84-5.21 2.84-7.67 0-.76-.05-1.47-.17-2.05H12.48z";
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
      <path d={path} />
    </svg>
  );
}

type CardsProps = {
  summary: UserAuthenticationSummary | null;
  error: string;
  canDisconnect: boolean;
  canCleanupAnonymised: boolean;
  busy: boolean;
  onDisconnect: (provider: SignInProvider, name: string) => void;
  onCleanupAnonymised: (provider: SignInProvider, name: string) => void;
};

/** "Connected Sign-in Methods": sits beside Authentication & MFA. */
export function ConnectedSignInMethodsCard({
  summary,
  error,
  canDisconnect,
  canCleanupAnonymised,
  busy,
  onDisconnect,
  onCleanupAnonymised,
}: CardsProps) {
  const canDisconnectForAccount = canDisconnect && !summary?.authentication_disabled;
  const canCleanupForAccount = canCleanupAnonymised && summary?.authentication_disabled;
  const usable =
    summary &&
    (summary.password.available ||
      summary.passkeys.count > 0 ||
      summary.providers.some((item) => item.connected && item.enabled_in_environment));
  return (
    <section className="cc-user-profile-card" id="sign-in-methods" aria-labelledby="cc-sign-in-methods-title">
      <div className="cc-user-profile-card-heading">
        <span className="cc-user-profile-card-icon"><Link2 size={19} /></span>
        <h2 id="cc-sign-in-methods-title">Connected Sign-in Methods</h2>
      </div>
      {error ? (
        <div className="cc-user-profile-card-body"><CcNotice tone="error">{error}</CcNotice></div>
      ) : !summary ? (
        <div className="cc-user-profile-card-body"><CcLoadingState label="Loading sign-in methods…" /></div>
      ) : (
        <>
          {summary.authentication_disabled && (
            <div className="cc-user-profile-card-body">
              <CcNotice tone="warning">
                <strong>Account anonymised</strong><br />
                Authentication access has been permanently disabled. Historical associations are not active sign-in methods.
              </CcNotice>
            </div>
          )}
          <ul className="cc-user-sign-in-list">
            {summary.providers.map((item) => (
              <li key={item.provider} className="cc-user-sign-in-item">
                <span className="cc-user-sign-in-icon"><ProviderIcon provider={item.provider} /></span>
                <div className="cc-user-sign-in-copy">
                  <strong>{item.name}</strong>
                  {item.connected && !summary.authentication_disabled ? (
                    <small>Connected {when(item.connected_at)} · Last used {when(item.last_used_at, "not recorded")}</small>
                  ) : item.connected && summary.authentication_disabled ? (
                    <small>Connected historically · Authentication disabled</small>
                  ) : (
                    <small>No {item.name} account is connected.</small>
                  )}
                  {item.connected && !item.enabled_in_environment && (
                    <small className="cc-user-sign-in-warning">
                      {item.name} sign-in is turned off in this environment, so this connection cannot be used right now.
                    </small>
                  )}
                </div>
                <CcBadge tone={item.connected ? "success" : "neutral"}>{item.connected ? "Connected" : "Not connected"}</CcBadge>
                {item.connected && canDisconnectForAccount && (
                  <button
                    type="button"
                    className="cc-user-sign-in-disconnect"
                    disabled={busy}
                    onClick={() => onDisconnect(item.provider, item.name)}
                  >
                    Disconnect<span className="cc-visually-hidden"> {item.name}</span>
                  </button>
                )}
                {item.connected && canCleanupForAccount && (
                  <button
                    type="button"
                    className="cc-user-sign-in-disconnect"
                    disabled={busy}
                    onClick={() => onCleanupAnonymised(item.provider, item.name)}
                  >
                    Disconnect<span className="cc-visually-hidden"> {item.name}</span>
                  </button>
                )}
              </li>
            ))}
            <li className="cc-user-sign-in-item">
              <span className="cc-user-sign-in-icon"><KeyRound size={18} aria-hidden="true" /></span>
              <div className="cc-user-sign-in-copy">
                <strong>Password</strong>
                <small>
                  {summary.authentication_disabled
                    ? "Password sign-in is disabled for this account."
                    : summary.password.available
                    ? `Password sign-in is available · Last changed ${when(summary.password.changed_at, "not recorded")}`
                    : "No password is set for this account."}
                </small>
              </div>
              <CcBadge tone={summary.password.available ? "success" : "neutral"}>
                {summary.authentication_disabled ? "Disabled" : summary.password.available ? "Available" : "Not set"}
              </CcBadge>
            </li>
            <li className="cc-user-sign-in-item">
              <span className="cc-user-sign-in-icon"><Fingerprint size={18} aria-hidden="true" /></span>
              <div className="cc-user-sign-in-copy">
                <strong>Passkeys</strong>
                <small>
                  {summary.authentication_disabled
                    ? "Passkeys have been revoked."
                    : summary.passkeys.count
                    ? `${summary.passkeys.count} registered · Last used ${when(summary.passkeys.last_used_at, "not recorded")}`
                    : "No passkeys are registered."}
                </small>
              </div>
              <CcBadge tone={summary.passkeys.count ? "success" : "neutral"}>
                {summary.authentication_disabled ? "Revoked" : summary.passkeys.count ? `${summary.passkeys.count} registered` : "None"}
              </CcBadge>
            </li>
          </ul>
          {!usable && (
            <div className="cc-user-profile-card-body">
              <CcNotice tone="warning">
                No sign-in method is currently usable in this environment. The user may be unable to sign in.
              </CcNotice>
            </div>
          )}
          <small className="cc-user-security-note">
            Disconnecting removes the link between the provider account and MyKhaya. It does not revoke access at
            Apple or Google. For anonymised accounts, this is historical authentication cleanup only and does not
            change the tombstone or account lifecycle. Provider account identifiers and email addresses are never shown here.
          </small>
        </>
      )}
    </section>
  );
}

type SupportProps = {
  summary: UserAuthenticationSummary | null;
  canRevokeSessions: boolean;
  busy: boolean;
  onRevokeSessions: () => void;
};

/** Sessions, native app registrations and recent authentication activity. */
export function AuthenticationSupportCards({ summary, canRevokeSessions, busy, onRevokeSessions }: SupportProps) {
  if (!summary) return null;
  const { sessions } = summary;
  return (
    <div className="cc-user-auth-support">
      <div className="cc-user-auth-support-grid">
        <section className="cc-user-profile-card" aria-labelledby="cc-user-sessions-title">
          <div className="cc-user-profile-card-heading">
            <span className="cc-user-profile-card-icon"><MonitorSmartphone size={19} /></span>
            <h2 id="cc-user-sessions-title">Sessions &amp; Trusted Devices</h2>
          </div>
          <dl className="cc-user-profile-list">
            <div><dt>Active sessions</dt><dd>{sessions.active_sessions}</dd></div>
            <div><dt>Trusted devices</dt><dd>{sessions.trusted_devices}</dd></div>
            <div><dt>Latest session activity</dt><dd>{when(sessions.last_session_activity_at, "No active session")}</dd></div>
          </dl>
          {canRevokeSessions && (
            <div className="cc-user-auth-card-actions">
              <button
                type="button"
                className="cc-user-sign-in-disconnect"
                disabled={busy || (sessions.active_sessions === 0 && sessions.trusted_devices === 0)}
                onClick={onRevokeSessions}
              >
                <ShieldOff size={15} aria-hidden="true" /> Revoke all sessions
              </button>
            </div>
          )}
        </section>
        <section className="cc-user-profile-card" aria-labelledby="cc-user-native-title">
          <div className="cc-user-profile-card-heading">
            <span className="cc-user-profile-card-icon"><Smartphone size={19} /></span>
            <h2 id="cc-user-native-title">App &amp; Push Registrations</h2>
          </div>
          <dl className="cc-user-profile-list cc-user-auth-native">
            {summary.native_apps.map((app) => (
              <div key={app.platform}>
                <dt>{app.label} App</dt>
                <dd>
                  <CcBadge tone={app.active_registrations ? "success" : "neutral"}>
                    {app.active_registrations ? `${app.active_registrations} registered` : "Not registered"}
                  </CcBadge>
                  {app.push_environments.length > 0 && <span className="is-muted">{app.push_environments.join(", ")}</span>}
                  <small>
                    {app.last_seen_at ? `Last seen ${when(app.last_seen_at)}` : "Not seen yet"}
                    {app.disabled_registrations ? ` · ${app.disabled_registrations} disabled` : ""}
                  </small>
                </dd>
              </div>
            ))}
            <div><dt>Web push</dt><dd>{summary.web_push_subscriptions ? `${summary.web_push_subscriptions} active` : "None"}</dd></div>
          </dl>
          <small className="cc-user-security-note">App versions are not recorded. Push tokens and device identifiers are never shown.</small>
        </section>
      </div>
      <section className="cc-user-profile-card" aria-labelledby="cc-user-auth-activity-title">
        <div className="cc-user-profile-card-heading">
          <span className="cc-user-profile-card-icon"><History size={19} /></span>
          <h2 id="cc-user-auth-activity-title">Recent Authentication Activity</h2>
          <Link className="cc-user-profile-link-button" href="/audit">Audit log</Link>
        </div>
        <div className="cc-user-activity-list">
          {summary.recent_events.length ? (
            summary.recent_events.map((event, index) => (
              <div className="cc-user-activity-item" key={`${event.occurred_at}-${index}`}>
                <span className={`cc-user-activity-dot is-${event.outcome}`} aria-hidden="true" />
                <div>
                  <strong>{event.label}</strong>
                  <small>
                    {when(event.occurred_at)}
                    {event.outcome === "failure" ? " · Failed" : ""}
                    {event.initiated_by === "administrator" ? " · PCC administrator" : ""}
                  </small>
                </div>
              </div>
            ))
          ) : (
            <p className="cc-user-profile-empty">No recent authentication activity is recorded.</p>
          )}
        </div>
        <small className="cc-user-security-note">
          Failed password attempts and passkey changes are not recorded per user, so they do not appear here.
        </small>
      </section>
    </div>
  );
}
