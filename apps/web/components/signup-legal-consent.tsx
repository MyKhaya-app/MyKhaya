import Link from "next/link";
import type { PublicLegalDocumentSummary } from "@mykhaya/api-client";

export const LEGAL_PAGE_BY_KEY: Record<string, string> = {
  terms: "/legal/terms",
  privacy: "/legal/privacy",
  children_privacy: "/legal/children",
  cookies: "/legal/cookies",
  founding_beta_terms: "/legal/founding-beta-terms",
};

export function legalPageHref(key: string): string {
  return LEGAL_PAGE_BY_KEY[key] ?? `/legal/${key}`;
}

/** The documents a new account must accept: one checkbox each. Unchanged
 *  rule, shared so /register and the Apple/Google choice step cannot drift. */
export function requiredContractualDocuments(
  documents: PublicLegalDocumentSummary[],
): PublicLegalDocumentSummary[] {
  return documents.filter(
    (document) =>
      document.audience === "adult" &&
      document.acceptance_required &&
      document.action_verb === "accept" &&
      document.scope === "global",
  );
}

/** One checkbox row per required contractual document (driven by the
 *  published documents, never pre-ticked, version always visible), then the
 *  informational notices as links. */
export function SignupLegalConsent({
  documents,
  checked,
  onChange,
  required = false,
  betaTermsNote,
  noticeConfirmation = false,
}: {
  documents: PublicLegalDocumentSummary[];
  checked: Record<string, boolean>;
  onChange: (key: string, value: boolean) => void;
  /** Adds the native required attribute (the /register form). */
  required?: boolean;
  /** Founding Beta: when the Beta Terms are reviewed. "email" for the email
   *  route (/register, after verification); "home" for the Apple or Google
   *  route, where Beta enrolment follows sign-in directly. */
  betaTermsNote?: "email" | "home";
  /** "By creating an account, you confirm …". */
  noticeConfirmation?: boolean;
}) {
  return (
    <div className="signup-consent">
      {requiredContractualDocuments(documents).map((document) => (
        <label className="signup-check-row" key={document.key}>
          <input
            type="checkbox"
            required={required}
            checked={checked[document.key] === true}
            onChange={(event) => onChange(document.key, event.target.checked)}
          />
          <span>
            I agree to the <Link href={legalPageHref(document.key)}>{document.display_name}</Link>{" "}
            ({document.current_version ? `v${document.current_version}` : "current version"}).
          </span>
        </label>
      ))}
      <p className="signup-consent-notices">
        Read our <Link href={legalPageHref("privacy")}>Privacy Notice</Link>,{" "}
        <Link href={legalPageHref("children_privacy")}>Family &amp; Children&rsquo;s Privacy Notice</Link>{" "}
        and <Link href={legalPageHref("cookies")}>Cookie Policy</Link>.
        {betaTermsNote && (
          <>
            {" "}You&rsquo;ll review the <Link href={legalPageHref("founding_beta_terms")}>Founding Beta Terms</Link>{" "}
            {betaTermsNote === "email" ? "after verifying your email." : "before your Home is enrolled."}
          </>
        )}
        {noticeConfirmation && (
          <> By creating an account, you confirm that these notices have been made available to you.</>
        )}
      </p>
    </div>
  );
}
