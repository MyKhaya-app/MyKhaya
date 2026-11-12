"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import type { PublicLegalDocumentSummary } from "@mykhaya/api-client";
import { FormStatus } from "./form-status";
import { AppleMark, GoogleMark } from "./provider-marks";
import { SignupBrandPanel, signupSteps } from "./signup-brand-panel";
import { SignupLegalConsent, requiredContractualDocuments } from "./signup-legal-consent";
import "@/app/brand-fonts.css";
import "@/app/auth-tokens.css";
import "@/app/signup-screen.css";

export type ProviderRecoveryOptions = {
  can_register: boolean;
  provider_email: string | null;
  display_name: string | null;
};

type Choice = "new" | "existing";

const PROVIDER_NAME = { apple: "Apple", google: "Google" } as const;

/** Initials for the identity avatar: from the provider's display name, else
 *  the first letter of the email, else nothing (the provider mark shows). */
export function identityInitials(displayName: string | null, email: string | null): string {
  const words = (displayName ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length) return words.slice(0, 2).map((word) => word[0]!.toUpperCase()).join("");
  const first = (email ?? "").trim()[0];
  return first ? first.toUpperCase() : "";
}

/** Partly masks the local part of an email ("an…@example.com"). Only ever
 *  applied to the address the API already returned for this sign-in. */
export function maskEmail(email: string): string {
  const at = email.lastIndexOf("@");
  if (at <= 0) return email;
  const local = email.slice(0, at);
  const visible = local.length > 2 ? local.slice(0, 2) : local.slice(0, 1);
  return `${visible}…${email.slice(at)}`;
}

/**
 * The Apple/Google account choice after a provider sign-in that is not yet
 * linked to a MyKhaya account (web ?apple=choose / ?google=choose and the
 * native-shell recovery). Presentation only: every action is one of the
 * sign-in page's existing callbacks, unchanged.
 */
export function ProviderAccountChoice({
  provider,
  recovery,
  beta,
  legalDocuments,
  legalChecked,
  onLegalChange,
  legalLoading,
  legalLoadFailed,
  displayName,
  onDisplayNameChange,
  busy,
  error,
  linking,
  onChooseNew,
  onChooseExisting,
  onLeaveExisting,
  onCreate,
  onBack,
  onSwitch,
  signIn,
  idPrefix,
}: {
  provider: "apple" | "google";
  /** null while the options are loading (or if they failed to load). */
  recovery: ProviderRecoveryOptions | null;
  beta: boolean;
  legalDocuments: PublicLegalDocumentSummary[];
  legalChecked: Record<string, boolean>;
  onLegalChange: (key: string, value: boolean) => void;
  legalLoading: boolean;
  legalLoadFailed: boolean;
  displayName: string;
  onDisplayNameChange: (value: string) => void;
  busy: boolean;
  error: string;
  /** True once "I already have an account" has moved on to signing in. */
  linking: boolean;
  /** "I'm new" selected: prepares account creation (native: loads the legal documents). */
  onChooseNew?: () => void;
  /** "Continue to sign in": starts the existing link-by-sign-in path. */
  onChooseExisting: () => void;
  /** Back from signing in to the choice. */
  onLeaveExisting: () => void;
  onCreate: () => void;
  onBack: () => void;
  /** Cancels this attempt and restarts the same provider. */
  onSwitch: () => void;
  /** The sign-in page's existing password form, shown while linking. */
  signIn: ReactNode;
  /** Prefix for element ids, unique per provider path. */
  idPrefix: string;
}) {
  const providerName = PROVIDER_NAME[provider];
  const Mark = provider === "apple" ? AppleMark : GoogleMark;
  const steps = signupSteps(beta, "provider");
  const canRegister = recovery?.can_register === true;
  const [choice, setChoice] = useState<Choice>("new");
  const userChanged = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const latestOnChooseNew = useRef(onChooseNew);
  latestOnChooseNew.current = onChooseNew;

  // Account creation is the default when it is allowed; otherwise linking is
  // the only route, so it is selected and the "new" card is not offered.
  useEffect(() => {
    if (recovery && !recovery.can_register) setChoice("existing");
  }, [recovery]);

  // Selecting "new" (including by default) prepares creation exactly as the
  // former "Create your account" button did.
  useEffect(() => {
    if (choice === "new" && canRegister) latestOnChooseNew.current?.();
  }, [choice, canRegister]);

  // Focus follows what the person just revealed, never on first render.
  useEffect(() => {
    if (!userChanged.current) return;
    if (choice === "new") nameInput.current?.focus();
  }, [choice]);
  useEffect(() => {
    if (linking) document.getElementById("signin-email")?.focus();
  }, [linking]);

  function select(next: Choice) {
    userChanged.current = true;
    if (next === "new" && linking) onLeaveExisting();
    setChoice(next);
  }

  const required = requiredContractualDocuments(legalDocuments);
  const consentComplete =
    !legalLoading &&
    !legalLoadFailed &&
    required.every((document) => Boolean(document.current_version_id && legalChecked[document.key]));
  const createDisabled = busy || !consentComplete;

  function submitOnEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && !createDisabled) {
      event.preventDefault();
      onCreate();
    }
  }

  const primaryName = recovery?.display_name?.trim()
    || (recovery?.provider_email ? maskEmail(recovery.provider_email) : `Your ${providerName} account`);
  const secondaryEmail = recovery?.display_name?.trim() && recovery.provider_email
    ? maskEmail(recovery.provider_email)
    : null;
  const initials = identityInitials(recovery?.display_name ?? null, recovery?.provider_email ?? null);

  return (
    <main className={`signup-screen signin-page signup-choice-screen${beta ? " is-beta" : ""}`}>
      <SignupBrandPanel beta={beta} steps={steps} current={1} />
      <div className="signup-main">
        <div className="signup-topbar signup-topbar--start">
          <button type="button" className="signup-icon-button" onClick={onBack} disabled={busy} aria-label="Back to sign in">
            <ArrowLeft size={22} strokeWidth={2} aria-hidden="true" />
            <span className="signup-icon-button-text" aria-hidden="true">Back</span>
          </button>
          <p className="signup-progress signup-progress--centre">Step 2 of 3</p>
          <span className="signup-topbar-spacer" aria-hidden="true" />
        </div>
        <div className="signup-progress-track" aria-hidden="true"><span /></div>
        <div className="signup-body">
          <div className="signup-column">
            {recovery && (
              <div className="signup-identity">
                <span className="signup-avatar" aria-hidden="true">{initials || <Mark size={20} />}</span>
                <span className="signup-identity-text">
                  <strong>{primaryName}</strong>
                  <span className="signup-identity-provider">
                    <Mark size={14} />
                    Signed in with {providerName}
                  </span>
                  {secondaryEmail && <span className="signup-identity-email">{secondaryEmail}</span>}
                </span>
                <button type="button" className="signup-link-button" onClick={onSwitch} disabled={busy} aria-label={`Switch ${providerName} account`}>
                  Switch
                </button>
              </div>
            )}
            <header className="signup-heading">
              {canRegister || !recovery ? (
                <>
                  <h1>Welcome to MyKhaya</h1>
                  <p>Is this a new account, or do you already use MyKhaya?</p>
                </>
              ) : (
                <>
                  <h1>Continue with {providerName}</h1>
                  <p>
                    New account creation is currently unavailable for this {providerName} sign-in. You can still link{" "}
                    {providerName} to an existing MyKhaya account.
                  </p>
                </>
              )}
            </header>
            {!recovery && !error && (
              <p className="signup-notice" role="status">Checking your {providerName} sign-in…</p>
            )}
            {recovery && (
              <fieldset className="signup-choice">
                <legend className="signup-visually-hidden">How would you like to continue?</legend>
                {canRegister && (
                  <div className={`signup-choice-card${choice === "new" ? " is-selected" : ""}`}>
                    <label className="signup-choice-option">
                      <input
                        type="radio"
                        name={`${idPrefix}-account-choice`}
                        value="new"
                        checked={choice === "new"}
                        onChange={() => select("new")}
                        disabled={busy}
                      />
                      <span className="signup-choice-copy">
                        <span className="signup-choice-title">
                          I&rsquo;m new to MyKhaya
                          {beta && <span className="signup-badge">Founding Beta</span>}
                        </span>
                        <span>
                          {beta ? "Create an account with complimentary Ultimate access" : "Create your MyKhaya account"}
                        </span>
                      </span>
                    </label>
                    {choice === "new" && (
                      <div className="signup-choice-details">
                        <div className="signup-field">
                          <label htmlFor={`${idPrefix}-display-name`}>Your name</label>
                          <input
                            ref={nameInput}
                            id={`${idPrefix}-display-name`}
                            value={displayName}
                            maxLength={100}
                            autoComplete="name"
                            required
                            onChange={(event) => onDisplayNameChange(event.target.value)}
                            onKeyDown={submitOnEnter}
                          />
                        </div>
                        {legalLoading ? (
                          <p className="signup-notice" role="status">Loading the current legal documents…</p>
                        ) : legalLoadFailed ? (
                          <p className="signup-notice" role="status">
                            The current legal documents could not be loaded. Go back and try again.
                          </p>
                        ) : (
                          <SignupLegalConsent
                            documents={legalDocuments}
                            checked={legalChecked}
                            onChange={onLegalChange}
                            betaTermsNote={beta ? "home" : undefined}
                            noticeConfirmation
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}
                <div className={`signup-choice-card${choice === "existing" ? " is-selected" : ""}`}>
                  <label className="signup-choice-option">
                    <input
                      type="radio"
                      name={`${idPrefix}-account-choice`}
                      value="existing"
                      checked={choice === "existing"}
                      onChange={() => select("existing")}
                      disabled={busy}
                    />
                    <span className="signup-choice-copy">
                      <span className="signup-choice-title">I already have an account</span>
                      <span>Link {providerName} so you can sign in either way.</span>
                    </span>
                  </label>
                  {choice === "existing" && (
                    <div className="signup-choice-details">
                      <p>
                        Sign in below with your existing MyKhaya email and password. {providerName} will be linked only
                        after that authentication succeeds.
                      </p>
                      {linking && signIn}
                    </div>
                  )}
                </div>
              </fieldset>
            )}
            {!linking && <FormStatus error={error} />}
            {recovery && !linking && (
              <div className="signup-sticky-actions">
                {choice === "new" && canRegister ? (
                  <button type="button" className="signup-primary" onClick={onCreate} disabled={createDisabled}>
                    {busy ? "Creating account…" : "Create account"}
                  </button>
                ) : (
                  <button type="button" className="signup-primary" onClick={onChooseExisting} disabled={busy}>
                    Continue to sign in
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
