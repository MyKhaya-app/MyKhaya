"use client";
import { Fragment, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import QRCode from "qrcode";
import type { Passkey } from "@mykhaya/shared-types";
import { Check, ChevronDown, ChevronRight, ChevronUp, KeyRound, Laptop, Mail, Monitor, Smartphone } from "lucide-react";
import { SettingsPage } from "@/components/settings-page";
import { AppleMark, GoogleMark } from "@/components/provider-marks";
import {
  biometricLabel,
  biometricSignInAvailable,
  clearBiometricHint,
  clearEnrolledPasskeyId,
  createPasskey,
  getEnrolledPasskeyId,
  passkeyWasCancelled,
  setBiometricHint,
  setEnrolledPasskeyId,
} from "@/components/passkey-client";
import { isNativeShell } from "@/components/native-runtime";
import { QuickSignIn } from "@/components/quick-sign-in";
import { nativeExternalAssertion, nativeExternalBrowserStart, nativeExternalExchange, nativeExternalRedeem, nativeExternalStart } from "@/components/native-auth";
import {
  classifyNativeProviderFailure,
  logNativeProviderFailure,
  newNativeAuthCorrelationId,
  type NativeProviderStage,
} from "@/components/native-provider-errors";
import { nativePlatform } from "@/components/native-runtime";
import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";

type Device = {
  id: string;
  device_name: string;
  platform: string;
  user_agent: string;
  last_used_at: string;
  current: boolean;
};

type MfaStatus = {
  required: boolean;
  allowed_methods: ("totp" | "email")[];
  email_available: boolean;
  email_destination: string | null;
  totp_enabled: boolean;
  can_disable_totp: boolean;
  usable_methods: ("totp" | "email")[];
  preferred_method: "totp" | "email" | null;
};

type TotpSetup = { provisioning_uri: string; manual_key: string };
type ExternalIdentity = {
  provider: "apple" | "google";
  provider_email: string | null;
  provider_email_verified: boolean;
  linked_at: string;
  last_used_at: string | null;
};

// The current session plus this many of the most recently active other
// sessions are listed before "Show all devices". Collapsing the list is
// presentation only: it never signs anything out.
const COLLAPSED_OTHER_DEVICES = 2;

// The API's default when a client sends no device name (see
// issue_trusted_device). Not a meaningful label, so the platform is used.
const DEFAULT_DEVICE_NAME = "MyKhaya device";

function formatDate(value: string) {
  return new Date(value).toLocaleDateString();
}

// Long addresses wrap after "@" and before dots rather than mid-word;
// overflow-wrap remains the fallback for a single very long segment.
function BreakableEmail({ value }: { value: string }) {
  const parts = value.split(/(?<=@)|(?=\.)/);
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 && <wbr />}
          {part}
        </Fragment>
      ))}
    </>
  );
}

function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: "success" | "neutral" }) {
  return (
    <span className={`security-status-badge security-status-badge-${tone}`}>
      {tone === "success" && <Check size={15} strokeWidth={2.4} aria-hidden="true" />}
      {children}
    </span>
  );
}

// Metadata parts ("Web/PWA", "Last active 05/11/2026") never break
// internally; when a row is narrow they wrap as whole parts.
function MetaParts({ parts }: { parts: (string | null | undefined | false)[] }) {
  const values = parts.filter((part): part is string => Boolean(part));
  if (values.length === 0) return null;
  return (
    <span className="security-row-meta">
      {values.map((part, index) => (
        <span className="security-meta-part" key={part}>
          {part}
          {index < values.length - 1 ? " ·" : ""}
        </span>
      ))}
    </span>
  );
}

function SecurityRow({
  icon,
  iconClassName = "",
  title,
  children,
  aside,
  className = "",
}: {
  icon: ReactNode;
  iconClassName?: string;
  title: ReactNode;
  children?: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <li className={`security-row${aside ? "" : " security-row-no-aside"}${className ? ` ${className}` : ""}`}>
      <span className={`security-row-icon${iconClassName ? ` ${iconClassName}` : ""}`} aria-hidden="true">
        {icon}
      </span>
      <div className="security-row-copy">
        <strong className="security-row-title">{title}</strong>
        {children}
      </div>
      {aside && <div className="security-row-aside">{aside}</div>}
    </li>
  );
}

function isMobilePlatform(platform: string) {
  const value = platform.toLowerCase();
  return value.includes("phone") || value.includes("ios") || value.includes("android");
}

function DeviceIcon({ platform }: { platform: string }) {
  const value = platform.toLowerCase();
  const Icon = isMobilePlatform(platform)
    ? Smartphone
    : value.includes("web") || value.includes("mac") || value.includes("windows") || value.includes("linux")
      ? Laptop
      : Monitor;
  return <Icon size={22} strokeWidth={1.75} />;
}

// Only what the API actually knows: a client-supplied device name when one
// was sent, otherwise a label derived from the recorded platform.
function deviceLabel(device: Device) {
  if (device.device_name && device.device_name !== DEFAULT_DEVICE_NAME) return device.device_name;
  const value = device.platform.toLowerCase();
  if (value === "ios") return "iOS device";
  if (value === "android") return "Android device";
  if (value.includes("web")) return "Web browser";
  return device.platform || DEFAULT_DEVICE_NAME;
}

function devicePlatformDetail(device: Device, label: string) {
  return label.toLowerCase().includes(device.platform.toLowerCase()) ? null : device.platform;
}

export default function Security() {
  const params = useSearchParams();
  const [devices, setDevices] = useState<Device[]>([]);
  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [error, setError] = useState("");
  const [passkeyError, setPasskeyError] = useState("");
  const [message, setMessage] = useState("");
  const [biometricBusy, setBiometricBusy] = useState(false);
  // Undecided while the async platform check runs — deliberately not "no",
  // so the Enable button doesn't flash in and immediately vanish on a
  // device that does have Face ID/Touch ID/Windows Hello.
  const [biometricAvailable, setBiometricAvailable] = useState<boolean | null>(null);
  const [labelText, setLabelText] = useState("biometrics");
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [totpSetup, setTotpSetup] = useState<TotpSetup | null>(null);
  const [totpQr, setTotpQr] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaError, setMfaError] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthBusy, setReauthBusy] = useState(false);
  const [reauthNeeded, setReauthNeeded] = useState(false);
  const [identities, setIdentities] = useState<ExternalIdentity[]>([]);
  const [identitiesLoaded, setIdentitiesLoaded] = useState(false);
  // null while unresolved: a Connect action is only offered once the
  // provider is known to be enabled, never shown and then withdrawn.
  const [providerAvailability, setProviderAvailability] = useState<Record<"apple" | "google", boolean> | null>(null);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [devicesExpanded, setDevicesExpanded] = useState(false);
  const [passkeysOpen, setPasskeysOpen] = useState(false);
  const [passwordAvailable, setPasswordAvailable] = useState(false);
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const nativeLinkTransaction = useRef<string | null>(null);
  const appleLinkTransaction = params.get("apple") === "link_required" ? params.get("transaction") : null;

  const native = isNativeShell();

  useEffect(() => {
    api.devices().then((value) => {
      setDevices(value);
      setDevicesLoaded(true);
    }).catch(() => setError("Could not load your signed-in devices."));
    api.passkeys().then(setPasskeys).catch(() => setError("Could not load your biometric sign-in status."));
    api.me().then((user) => setAccountEmail(user.email)).catch(() => {});
    api.externalIdentities().then((result) => {
      setIdentities(result.identities);
      setPasswordAvailable(result.password_available);
      setIdentitiesLoaded(true);
    }).catch(() => setError("Could not load your sign-in methods."));
    // Web MFA settings are plain authenticated API calls (cookie or native
    // bearer transport alike), so they are managed from either shell.
    api.mfaStatus().then(setMfaStatus).catch(() => setError("Could not load your multi-factor authentication status."));
    // Browser WebAuthn feature-detection only — the native shell renders
    // QuickSignIn (native Face ID/Touch ID, no WebAuthn involved) and never
    // offers "Add passkey", and must never invoke
    // navigator.credentials/PublicKeyCredential at all: that API has been
    // observed to hang inside the Capacitor WKWebView, which is exactly
    // the "Quick Sign-In freezes the app" defect this guard fixes.
    if (native) {
      // Matches the login screen: the native shell always offers both
      // providers through their native SDK or system-browser flows.
      setProviderAvailability({ apple: true, google: true });
      return;
    }
    api.authProviders()
      .then((result) => setProviderAvailability({
        apple: result.providers.some((item) => item.provider === "apple" && item.enabled),
        google: result.providers.some((item) => item.provider === "google" && item.enabled),
      }))
      .catch(() => setProviderAvailability({ apple: false, google: false }));
    biometricSignInAvailable().then(setBiometricAvailable);
    setLabelText(biometricLabel());
  }, [native]);

  useEffect(() => {
    if (!native) return;
    let active = true;
    const listener = App.addListener("appUrlOpen", ({ url }) => {
      const expectedScheme = nativePlatform() === "ios"
        ? (window.location.hostname === "mykhaya.app" ? "mykhaya-prod" : "mykhaya")
        : (window.location.hostname === "mykhaya.app" ? "app.mykhaya.mobile.prod" : "app.mykhaya.mobile");
      let parsed: URL;
      try { parsed = new URL(url); } catch { return; }
      if (parsed.protocol !== `${expectedScheme}:` || parsed.hostname !== "auth" || parsed.pathname !== "/callback") return;
      const transactionId = parsed.searchParams.get("transaction");
      if (!transactionId || transactionId !== nativeLinkTransaction.current) return;
      void nativeExternalRedeem(transactionId)
        .then(async (result) => {
          if (!active) return;
          if (!("message" in result)) throw new Error("The provider link did not complete.");
          setMessage(result.message);
          const refreshed = await api.externalIdentities();
          if (active) setIdentities(refreshed.identities);
        })
        .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.message : "Could not connect the provider."); })
        .finally(() => { if (active) { nativeLinkTransaction.current = null; setIdentityBusy(false); } });
    });
    return () => { active = false; void listener.then((handle) => handle.remove()); };
  }, [native]);

  useEffect(() => {
    if (native || !appleLinkTransaction) return;
    let active = true;
    setIdentityBusy(true);
    setError("");
    void api.appleRecoveryLink(appleLinkTransaction)
      .then(async () => {
        if (!active) return;
        setMessage("Apple sign-in is now connected.");
        const result = await api.externalIdentities();
        if (active) setIdentities(result.identities);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof ApiError ? cause.message : "Could not connect Apple sign-in.");
      })
      .finally(() => {
        if (active) setIdentityBusy(false);
      });
    return () => {
      active = false;
    };
  }, [appleLinkTransaction, native]);

  async function setupAuthenticator() {
    setMfaBusy(true);
    setError("");
    setMfaError("");
    try {
      const setup = await api.totpSetup();
      setTotpSetup(setup);
      setTotpQr(await QRCode.toDataURL(setup.provisioning_uri, { margin: 1, width: 220 }));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setReauthNeeded(true);
        setMfaError("For your security, please verify your identity before setting up an authenticator app.");
      } else {
        setMfaError("Could not start authenticator setup. Please try again.");
      }
    } finally {
      setMfaBusy(false);
    }
  }

  async function confirmAuthenticator(event: FormEvent) {
    event.preventDefault();
    setMfaBusy(true);
    setError("");
    setMfaError("");
    try {
      setMfaStatus(await api.totpVerify(totpCode));
      setTotpSetup(null);
      setTotpQr(null);
      setTotpCode("");
      setMessage("Authenticator app is now set up.");
    } catch {
      setMfaError("That authenticator code isn't correct. Please try again.");
    } finally {
      setMfaBusy(false);
    }
  }

  async function disableAuthenticator() {
    if (!window.confirm("Turn off your authenticator app?")) return;
    setMfaBusy(true);
    setError("");
    setMfaError("");
    try {
      await api.removeTotp();
      setMfaStatus((value) => value && { ...value, totp_enabled: false, can_disable_totp: false });
      setMessage("Authenticator app has been turned off.");
    } catch {
      setMfaError("Could not turn off authenticator app. Please try again.");
    } finally {
      setMfaBusy(false);
    }
  }

  async function reauthenticate(event: FormEvent) {
    event.preventDefault();
    setReauthBusy(true);
    setMfaError("");
    try {
      await api.reauthenticate(reauthPassword);
      setReauthPassword("");
      setReauthNeeded(false);
      await setupAuthenticator();
    } catch (cause) {
      setMfaError(cause instanceof ApiError ? cause.message : "We couldn't verify your identity.");
    } finally {
      setReauthBusy(false);
    }
  }

  async function connectApple() {
    if (native) return linkNativeProvider("apple");
    setIdentityBusy(true);
    setError("");
    try {
      const result = await api.appleLinkStart();
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start Apple sign-in.");
      setIdentityBusy(false);
    }
  }

  async function disconnectApple() {
    if (!window.confirm("Disconnect Apple sign-in from this MyKhaya account?")) return;
    setIdentityBusy(true);
    setError("");
    try {
      await api.appleUnlink();
      setIdentities((value) => value.filter((identity) => identity.provider !== "apple"));
      setMessage("Apple sign-in has been disconnected.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not disconnect Apple sign-in.");
    } finally {
      setIdentityBusy(false);
    }
  }

  async function connectGoogle() {
    if (native) return linkNativeProvider("google");
    setIdentityBusy(true);
    setError("");
    try {
      const result = await api.googleLinkStart();
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start Google sign-in.");
      setIdentityBusy(false);
    }
  }

  async function linkNativeProvider(provider: "apple" | "google") {
    setIdentityBusy(true);
    setError("");
    let stage: NativeProviderStage = "start";
    const correlationId = newNativeAuthCorrelationId();
    try {
      const platform = nativePlatform();
      const useBrowser = (provider === "google" && platform === "ios") || (provider === "apple" && platform === "android");
      if (useBrowser) {
        const result = await nativeExternalBrowserStart(provider, "link");
        nativeLinkTransaction.current = result.transaction_id;
        await Browser.open({ url: result.authorization_url });
        return;
      }
      stage = "start";
      const started = await nativeExternalStart(provider, "link", correlationId);
      stage = "provider";
      const assertion = await nativeExternalAssertion(provider, started.nonce, started.client_id);
      stage = "exchange";
      const result = await nativeExternalExchange(started.transaction_id, assertion.identity_token, correlationId);
      stage = "follow_up";
      if (!("message" in result)) throw new Error("The provider link did not complete.");
      setMessage(result.message);
      const refreshed = await api.externalIdentities();
      setIdentities(refreshed.identities);
      setIdentityBusy(false);
    } catch (cause) {
      const failure = classifyNativeProviderFailure(cause, provider, stage, "link");
      logNativeProviderFailure(provider, stage, correlationId, failure);
      if (failure.userMessage) setError(failure.userMessage);
      setIdentityBusy(false);
    }
  }

  async function disconnectGoogle() {
    if (!window.confirm("Disconnect Google sign-in from this MyKhaya account?")) return;
    setIdentityBusy(true);
    setError("");
    try {
      await api.googleUnlink();
      setIdentities((value) => value.filter((identity) => identity.provider !== "google"));
      setMessage("Google sign-in has been disconnected.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not disconnect Google sign-in.");
    } finally {
      setIdentityBusy(false);
    }
  }

  async function choosePreferred(method: "totp" | "email") {
    setMfaBusy(true);
    setMfaError("");
    try {
      setMfaStatus(await api.setMfaPreference(method));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setMfaError("For your security, please verify your identity before changing this preference.");
      } else {
        setMfaError(cause instanceof ApiError ? cause.message : "Could not update your preferred method.");
      }
    } finally {
      setMfaBusy(false);
    }
  }

  // "Enabled on this device" — precisely the credential this browser
  // created (see getEnrolledPasskeyId), not just "the account has some
  // passkey somewhere". A credential id from a different device never
  // counts here, even though the account-level list below still shows it.
  const enrolledId = getEnrolledPasskeyId();
  const thisDevicePasskey = passkeys.find((row) => row.id === enrolledId) ?? null;

  async function enableBiometricSignIn() {
    setBiometricBusy(true);
    setPasskeyError("");
    try {
      const options = await api.passkeyRegistrationOptions();
      const credential = await createPasskey(options.options_json);
      const created = await api.passkeyRegistrationVerify(JSON.stringify(credential));
      setPasskeys((value) => [...value, created]);
      setEnrolledPasskeyId(created.id);
      const me = await api.me();
      setBiometricHint({
        userId: me.id,
        displayName: me.display_name,
        avatarVersion: me.avatar_version,
      });
      setMessage(`${labelText} is ready — you can use it next time you sign in.`);
    } catch (cause) {
      setPasskeyError(
        passkeyWasCancelled(cause)
          ? "Biometric sign-in setup was cancelled."
          : cause instanceof ApiError
            ? cause.message
            : "Could not set up biometric sign-in.",
      );
    } finally {
      setBiometricBusy(false);
    }
  }

  async function disableBiometricSignIn() {
    if (!thisDevicePasskey) return;
    if (
      !window.confirm(
        `Turn off biometric sign-in on this device? You can still sign in with your password.`,
      )
    )
      return;
    setBiometricBusy(true);
    setPasskeyError("");
    try {
      await api.revokePasskey(thisDevicePasskey.id);
      setPasskeys((value) => value.filter((item) => item.id !== thisDevicePasskey.id));
      clearEnrolledPasskeyId();
      clearBiometricHint();
      setMessage("Biometric sign-in has been turned off on this device.");
    } catch (cause) {
      setPasskeyError(cause instanceof ApiError ? cause.message : "Could not turn off this passkey.");
    } finally {
      setBiometricBusy(false);
    }
  }

  async function renamePasskey(passkey: Passkey) {
    const label = window.prompt("Name this device", passkey.label)?.trim();
    if (!label || label === passkey.label) return;
    try {
      const updated = await api.renamePasskey(passkey.id, label);
      setPasskeys((value) => value.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setPasskeyError(cause instanceof ApiError ? cause.message : "Could not rename this passkey.");
    }
  }

  async function revokeOtherPasskey(passkey: Passkey) {
    if (
      !window.confirm(`Remove biometric sign-in for "${passkey.label}"? That device will need your password again.`)
    )
      return;
    try {
      await api.revokePasskey(passkey.id);
      setPasskeys((value) => value.filter((item) => item.id !== passkey.id));
    } catch (cause) {
      setPasskeyError(cause instanceof ApiError ? cause.message : "Could not remove that passkey.");
    }
  }

  async function revoke(id: string) {
    setError("");
    try {
      await api.revokeDevice(id);
      setDevices((value) => value.filter((device) => device.id !== id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not sign out that device.");
    }
  }
  async function revokeOthers() {
    if (!window.confirm("Sign out every other device? This device stays signed in.")) return;
    setError("");
    try {
      await api.revokeOtherDevices();
      setDevices((value) => value.filter((device) => device.current));
      setMessage("Other devices have been signed out.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not sign out other devices.");
    }
  }

  const otherPasskeys = passkeys.filter((row) => row.id !== enrolledId);
  const usableMfaMethods = mfaStatus?.usable_methods ?? [];
  const multipleMfaMethods = usableMfaMethods.length > 1;
  const canPrefer = (method: "totp" | "email") =>
    multipleMfaMethods && mfaStatus?.preferred_method !== method && usableMfaMethods.includes(method);
  const isPreferred = (method: "totp" | "email") =>
    multipleMfaMethods && mfaStatus?.preferred_method === method;

  // The current session is whichever one the API marks current for this
  // request; the rest are listed most recently active first.
  const currentDevice = devices.find((device) => device.current) ?? null;
  const otherDevices = devices
    .filter((device) => !device.current)
    .sort((a, b) => new Date(b.last_used_at).getTime() - new Date(a.last_used_at).getTime());
  const hiddenDeviceCount = Math.max(0, otherDevices.length - COLLAPSED_OTHER_DEVICES);
  const visibleOtherDevices = devicesExpanded ? otherDevices : otherDevices.slice(0, COLLAPSED_OTHER_DEVICES);

  return (
    <SettingsPage title="Security" className="security-page">
      <div className="security-stack">
        {message && <p className="notice" role="status">{message}</p>}
        {error && <p className="notice error" role="alert">{error}</p>}

        <section className="card security-card" aria-labelledby="sign-in-methods-heading">
          <header className="security-card-header">
            <h2 id="sign-in-methods-heading">Sign-in methods</h2>
            <p className="security-card-intro">Choose the secure ways you can access your MyKhaya account.</p>
          </header>
          <ul className="security-list">
            <SecurityRow
              icon={<Mail size={22} strokeWidth={1.75} />}
              title="Email and password"
              aside={identitiesLoaded && (
                <StatusBadge tone={passwordAvailable ? "success" : "neutral"}>
                  {passwordAvailable ? "Connected" : "Not connected"}
                </StatusBadge>
              )}
            >
              <span className="security-row-detail">{accountEmail ? <BreakableEmail value={accountEmail} /> : "Your account email"}</span>
            </SecurityRow>
            {(["apple", "google"] as const).map((provider) => {
              const identity = identities.find((item) => item.provider === provider);
              const label = provider === "apple" ? "Apple" : "Google";
              const available = providerAvailability?.[provider];
              const disconnect = () => void (provider === "apple" ? disconnectApple() : disconnectGoogle());
              const connect = () => void (provider === "apple" ? connectApple() : connectGoogle());
              return (
                <SecurityRow
                  key={provider}
                  icon={provider === "apple" ? <AppleMark /> : <GoogleMark />}
                  iconClassName={`security-row-icon-${provider}`}
                  title={label}
                  aside={!identitiesLoaded ? null : identity ? (
                    <>
                      <StatusBadge tone="success">Connected</StatusBadge>
                      <button
                        className="secondary security-action"
                        aria-label={`Disconnect ${label}`}
                        disabled={identityBusy}
                        onClick={disconnect}
                      >
                        {identityBusy ? "Disconnecting…" : "Disconnect"}
                      </button>
                    </>
                  ) : available ? (
                    <button
                      className="security-action"
                      aria-label={`Connect ${label}`}
                      disabled={identityBusy}
                      onClick={connect}
                    >
                      {identityBusy ? "Connecting…" : "Connect"}
                    </button>
                  ) : available === false ? (
                    <StatusBadge>Unavailable</StatusBadge>
                  ) : null}
                >
                  {identity ? (
                    <>
                      {identity.provider_email && (
                        <span className="security-row-detail"><BreakableEmail value={identity.provider_email} /></span>
                      )}
                      <MetaParts
                        parts={[
                          `Linked ${formatDate(identity.linked_at)}`,
                          identity.last_used_at && `Last used ${formatDate(identity.last_used_at)}`,
                        ]}
                      />
                    </>
                  ) : identitiesLoaded ? (
                    <span className="security-row-detail">Not connected</span>
                  ) : null}
                </SecurityRow>
              );
            })}
          </ul>
          {params.get("apple") === "linked" && (
            <p className="notice" role="status">Apple sign-in is now connected.</p>
          )}
          {params.get("apple") === "link_required" && identityBusy && (
            <p className="notice" role="status">Finishing Apple sign-in connection…</p>
          )}
          {params.get("apple") === "error" && (
            <p className="notice error" role="alert">Apple sign-in could not be connected. Please try again.</p>
          )}
          {params.get("google") === "linked" && (
            <p className="notice" role="status">Google sign-in is now connected.</p>
          )}
          {params.get("google") === "error" && (
            <p className="notice error" role="alert">Google sign-in could not be connected. Please try again.</p>
          )}
        </section>

        <section className="card security-card" aria-labelledby="browser-mfa-heading">
          <header className="security-card-header">
            <h2 id="browser-mfa-heading">Multi-factor authentication</h2>
            <p className="security-card-intro">
              {!mfaStatus
                ? "Checking your verification methods…"
                : mfaStatus.required
                  ? "Multi-factor authentication is required for web sign-ins, including when using Apple or Google."
                  : "Web sign-ins can use an additional verification step."}
            </p>
          </header>
          {mfaStatus && (
            <>
              <ul className="security-list">
                <SecurityRow
                  className="security-mfa-status"
                  icon={<Smartphone size={22} strokeWidth={1.75} />}
                  title="Authenticator app"
                  aside={(isPreferred("totp") || !totpSetup) && (
                    <>
                      {isPreferred("totp") && <StatusBadge tone="success">Preferred</StatusBadge>}
                      {!totpSetup && (mfaStatus.totp_enabled ? (
                        mfaStatus.can_disable_totp && (
                          <button className="secondary security-action" disabled={mfaBusy} onClick={() => void disableAuthenticator()}>
                            Disable
                          </button>
                        )
                      ) : (
                        <button
                          className="secondary security-action"
                          aria-label="Set up authenticator app"
                          disabled={mfaBusy}
                          onClick={() => void setupAuthenticator()}
                        >
                          Set up
                        </button>
                      ))}
                    </>
                  )}
                >
                  <span className="security-row-detail">Use codes from your authenticator app.</span>
                  {!mfaStatus.totp_enabled && <span className="security-row-meta">Not set up</span>}
                  {mfaStatus.totp_enabled && !mfaStatus.can_disable_totp && (
                    <span className="security-row-meta">Required by your sign-in policy</span>
                  )}
                  {canPrefer("totp") && (
                    <button className="tertiary security-inline-action" disabled={mfaBusy} onClick={() => void choosePreferred("totp")}>
                      Make preferred
                    </button>
                  )}
                </SecurityRow>
                <SecurityRow
                  className="security-mfa-status"
                  icon={<Mail size={22} strokeWidth={1.75} />}
                  title="Email verification"
                  aside={mfaStatus.email_available && isPreferred("email") && (
                    <StatusBadge tone="success">Preferred</StatusBadge>
                  )}
                >
                  <span className="security-row-detail">
                    {mfaStatus.email_available
                      ? (mfaStatus.email_destination ? <BreakableEmail value={mfaStatus.email_destination} /> : "Verified account email")
                      : "No verified email address available"}
                  </span>
                  {mfaStatus.email_available && canPrefer("email") && (
                    <button className="tertiary security-inline-action" disabled={mfaBusy} onClick={() => void choosePreferred("email")}>
                      Make preferred
                    </button>
                  )}
                </SecurityRow>
              </ul>
              {totpSetup && (
                <form onSubmit={(event) => void confirmAuthenticator(event)} className="mfa-method security-panel">
                  <p>Scan this QR code with your authenticator app, or enter the setup key manually.</p>
                  {totpQr && <img src={totpQr} alt="Scan with your authenticator app" className="auth-mfa-qr" />}
                  <p>Setup key: <code>{totpSetup.manual_key}</code></p>
                  <label htmlFor="security-totp-code">Confirmation code</label>
                  <input id="security-totp-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required />
                  <button disabled={mfaBusy || totpCode.length !== 6}>{mfaBusy ? "Checking…" : "Confirm setup"}</button>
                </form>
              )}
              {reauthNeeded && (
                <form className="mfa-reauth security-panel" onSubmit={(event) => void reauthenticate(event)}>
                  <p>For your security, please verify your identity before setting up an authenticator app.</p>
                  <label htmlFor="mfa-reauth-password">Password</label>
                  <input id="mfa-reauth-password" type="password" value={reauthPassword} onChange={(event) => setReauthPassword(event.target.value)} autoComplete="current-password" required />
                  <button disabled={reauthBusy}>{reauthBusy ? "Verifying…" : "Verify identity"}</button>
                </form>
              )}
              {mfaError && <p className="notice error" role="alert">{mfaError}</p>}
            </>
          )}
        </section>

        <section className="card security-card security-passkeys-card" aria-labelledby="passkeys-heading">
          <div className="security-row security-card-row">
            <span className="security-row-icon" aria-hidden="true"><KeyRound size={22} strokeWidth={1.75} /></span>
            <div className="security-row-copy">
              <h2 id="passkeys-heading">Passkeys</h2>
              <span className="security-row-detail">Use a passkey to sign in securely.</span>
              <span className="security-row-meta">
                {passkeys.length === 0
                  ? "No passkeys set up"
                  : `${passkeys.length} ${passkeys.length === 1 ? "passkey" : "passkeys"} set up`}
              </span>
            </div>
            <div className="security-row-aside security-row-aside-inline">
              <button
                className="secondary security-action"
                aria-expanded={passkeysOpen}
                aria-controls="security-passkey-management"
                aria-label="Manage passkeys"
                onClick={() => setPasskeysOpen((value) => !value)}
              >
                Manage
              </button>
              <ChevronRight className="security-disclosure-chevron" size={20} strokeWidth={2} aria-hidden="true" />
            </div>
          </div>
          <div id="security-passkey-management" className="security-manage-panel" hidden={!passkeysOpen}>
            {native ? (
              <p className="security-panel-note">To add a passkey, open MyKhaya in a web browser.</p>
            ) : thisDevicePasskey ? (
              <div className="security-manage-row">
                <span className="security-row-detail">A passkey is enabled on this browser/device.</span>
                <button className="secondary security-action" disabled={biometricBusy} onClick={() => void disableBiometricSignIn()}>
                  {biometricBusy ? "Turning off…" : "Disable"}
                </button>
              </div>
            ) : biometricAvailable ? (
              <div className="security-manage-row">
                <span className="security-row-detail">Add a passkey for this browser or device.</span>
                <button className="security-action" disabled={biometricBusy} onClick={() => void enableBiometricSignIn()}>
                  {biometricBusy ? "Setting up…" : "Add passkey"}
                </button>
              </div>
            ) : biometricAvailable === false ? (
              <p className="security-panel-note">Passkeys aren&rsquo;t available on this browser or device. Your password still works as usual.</p>
            ) : null}
            {passkeyError && <p className="notice error" role="alert">{passkeyError}</p>}
            {otherPasskeys.length > 0 && (
              <>
                <h3 className="security-panel-heading">
                  {thisDevicePasskey ? "Passkeys on other devices" : "Your passkeys"}
                </h3>
                <ul className="security-list">
                  {otherPasskeys.map((passkey) => (
                    <li className="security-row security-passkey-item" key={passkey.id}>
                      <span className="security-row-icon" aria-hidden="true"><KeyRound size={20} strokeWidth={1.75} /></span>
                      <div className="security-row-copy">
                        <strong className="security-row-title">{passkey.label}</strong>
                        <MetaParts
                          parts={[
                            `Added ${formatDate(passkey.created_at)}`,
                            passkey.last_used_at && `Last used ${formatDate(passkey.last_used_at)}`,
                          ]}
                        />
                      </div>
                      <div className="security-passkey-actions">
                        <button className="tertiary security-action" aria-label={`Rename ${passkey.label}`} onClick={() => void renamePasskey(passkey)}>Rename</button>
                        <button className="secondary security-action" aria-label={`Remove ${passkey.label}`} onClick={() => void revokeOtherPasskey(passkey)}>Remove</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </section>

        {native && <QuickSignIn />}

        <section className="card security-card" aria-labelledby="devices-heading" id="devices">
          <header className="security-card-header">
            <div className="security-card-title-row">
              <h2 id="devices-heading">Signed-in devices</h2>
              {devicesLoaded && (
                <span className="security-count-badge">
                  {devices.length} {devices.length === 1 ? "session" : "sessions"}
                </span>
              )}
            </div>
            <p className="security-card-intro">Devices that are currently signed in to your account.</p>
          </header>
          <ul className="security-list security-device-list" id="security-device-list">
            {currentDevice && (
              <SecurityRow
                className="security-device-current"
                icon={<DeviceIcon platform={currentDevice.platform} />}
                title="This device"
                aside={<span className="security-current-badge">Current</span>}
              >
                <MetaParts parts={[currentDevice.platform, "Active now"]} />
              </SecurityRow>
            )}
            {visibleOtherDevices.map((device) => {
              const label = deviceLabel(device);
              const lastActive = formatDate(device.last_used_at);
              return (
                <SecurityRow
                  key={device.id}
                  icon={<DeviceIcon platform={device.platform} />}
                  title={label}
                  aside={(
                    <button
                      className="secondary security-action"
                      aria-label={`Sign out ${label}, last active ${lastActive}`}
                      onClick={() => void revoke(device.id)}
                    >
                      Sign out
                    </button>
                  )}
                >
                  <MetaParts parts={[devicePlatformDetail(device, label), `Last active ${lastActive}`]} />
                </SecurityRow>
              );
            })}
          </ul>
          {otherDevices.length > COLLAPSED_OTHER_DEVICES && (
            <button
              className="secondary security-wide-action"
              aria-expanded={devicesExpanded}
              aria-controls="security-device-list"
              onClick={() => setDevicesExpanded((value) => !value)}
            >
              {devicesExpanded ? (
                <><ChevronUp size={20} strokeWidth={2} aria-hidden="true" />Show fewer devices</>
              ) : (
                <><ChevronDown size={20} strokeWidth={2} aria-hidden="true" />Show all devices ({hiddenDeviceCount} more)</>
              )}
            </button>
          )}
          {otherDevices.length > 0 && (
            <button className="secondary security-wide-action security-signout-all" onClick={() => void revokeOthers()}>
              Sign out all other devices
            </button>
          )}
        </section>
      </div>
    </SettingsPage>
  );
}
