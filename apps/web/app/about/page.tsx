"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { App } from "@capacitor/app";
import { Cookie, FileText, Info, Shield, Users } from "lucide-react";
import {
  api,
  type LegalDocumentStatus,
  type LegalStatusResponse,
  type PublicLegalDocumentSummary,
} from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { SettingsPage } from "@/components/settings-page";
import { Logo } from "@/components/logo";
import { useBuildInfo } from "@/components/app-version";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { useNotificationPermission } from "@/components/use-notification-permission";
import { nativePushDiagnostics } from "@/components/native-push";
import {
  LEGAL_DOCUMENT_DESCRIPTION,
  type LegalRowPresentation,
  presentAdultLegalStatus,
  presentGuardianLegalStatus,
} from "@/components/legal-status-presentation";

const LEGAL_ROW_ICON: Record<string, typeof FileText> = {
  terms: FileText,
  privacy: Shield,
  children_privacy: Users,
  cookies: Cookie,
};

type NativeAppInfo = {
  version: string;
  build: string;
};

type PushDiagnostics = {
  tokenPresent: boolean;
  registered: boolean;
  lastRegisteredAt: string | null;
};

const PERMISSION_LABELS: Record<string, string> = {
  granted: "Granted",
  denied: "Off",
  not_requested: "Not requested",
  restricted: "Restricted",
  unsupported: "Unsupported",
};

// Only populated inside the native shell, from this session's in-memory
// registration state (populated by reconcileNativePush()/enableNativePush())
// plus a best-effort localStorage timestamp — never a fake/placeholder
// value while unknown, matching useNativeAppInfo()'s own convention above.
function useNativePushDiagnostics(): PushDiagnostics | null {
  const [diagnostics, setDiagnostics] = useState<PushDiagnostics | null>(null);

  useEffect(() => {
    if (!isNativeShell()) return;
    const { tokenPresent, registered } = nativePushDiagnostics();
    let lastRegisteredAt: string | null = null;
    try {
      lastRegisteredAt = window.localStorage.getItem("mykhaya.native.push.last-registered-at");
    } catch {
      lastRegisteredAt = null;
    }
    setDiagnostics({ tokenPresent, registered, lastRegisteredAt });
  }, []);

  return diagnostics;
}

// Only populated inside the Capacitor iOS shell, and only once App.getInfo()
// resolves — omitted entirely (never a fake value) while loading or on
// failure. See docs/architecture/adr/0012-capacitor-ios-shell.md.
function useNativeAppInfo(): NativeAppInfo | null {
  const [info, setInfo] = useState<NativeAppInfo | null>(null);

  useEffect(() => {
    if (!isNativeShell()) return;
    App.getInfo()
      .then((result) => setInfo({ version: result.version, build: result.build }))
      .catch(() => setInfo(null));
  }, []);

  return info;
}

/** Legal documents applicable to this account, with the exact recorded
 * action/date — a read-only presentation over GET /legal/documents +
 * GET /legal/status (mykhaya.routers.legal). Never alters legal evidence;
 * see components/legal-gate.tsx for the flow that actually records an
 * acceptance. */
function useLegalCompliance() {
  // Fetched directly (matching SettingsPage's own api.me() convention)
  // rather than via useAuth() — this hook must work wherever About renders,
  // and AuthProvider isn't guaranteed present around every test/host of
  // this component.
  const [user, setUser] = useState<User | null>(null);
  const [documents, setDocuments] = useState<PublicLegalDocumentSummary[] | null>(null);
  const [legalStatus, setLegalStatus] = useState<LegalStatusResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
    Promise.all([api.publicLegalDocuments(), api.legalStatus()])
      .then(([publishedDocuments, status]) => {
        setDocuments(publishedDocuments);
        setLegalStatus(status);
      })
      .catch(() => setError("Legal information could not be loaded right now."));
  }, []);

  const isChild = user?.principal_type === "managed_child";

  type Row = {
    key: string;
    documentKey: string;
    displayName: string;
    version: string;
    description: string;
    presentation: LegalRowPresentation;
    isTest: boolean;
  };

  const rows: Row[] = [];
  if (documents && legalStatus) {
    if (isChild) {
      // A managed child never sees adult Terms/contract documents — only
      // their own Family & Children's Privacy acknowledgement (§11/§18).
      const childDoc = documents.find((doc) => doc.key === "children_privacy");
      const ack = legalStatus.child_self?.child_acknowledgement;
      if (childDoc && ack) {
        rows.push({
          key: "children_privacy",
          documentKey: childDoc.key,
          displayName: childDoc.display_name,
          version: childDoc.current_version ?? "—",
          description: LEGAL_DOCUMENT_DESCRIPTION[childDoc.key] ?? "",
          presentation: presentAdultLegalStatus(ack),
          isTest: Boolean(ack.is_test),
        });
      }
    } else {
      for (const doc of documents) {
        if (doc.audience === "adult") {
          const entry = legalStatus.documents.find((d) => d.document_key === doc.key);
          if (!entry) continue;
          rows.push({
            key: doc.key,
            documentKey: doc.key,
            displayName: doc.display_name,
            version: doc.current_version ?? "—",
            description: LEGAL_DOCUMENT_DESCRIPTION[doc.key] ?? "",
            presentation: presentAdultLegalStatus(entry),
            isTest: Boolean(entry.is_test),
          });
        } else {
          // Child-audience document (Family & Children's Privacy) viewed by
          // an adult: shown as their own guardian_authorisation status,
          // aggregated across every child they guard — never as though the
          // adult personally "accepted" it (§15 distinction preserved).
          const guardianEntries = legalStatus.children
            .filter((child) => child.document_key === doc.key && child.guardian_authorisation)
            .map((child) => child.guardian_authorisation as LegalDocumentStatus);
          rows.push({
            key: doc.key,
            documentKey: doc.key,
            displayName: doc.display_name,
            version: doc.current_version ?? "—",
            description: LEGAL_DOCUMENT_DESCRIPTION[doc.key] ?? "",
            presentation: presentGuardianLegalStatus(guardianEntries),
            isTest: guardianEntries.some((entry) => Boolean(entry.is_test)),
          });
        }
      }
    }
  }

  return { rows, loading: !documents || !legalStatus, error };
}

/** "unknown" is `resolve_app_version()`'s deliberate last-resort fallback
 * (see apps/api/mykhaya/config.py) for when no package metadata, VERSION
 * file, or override can be found — genuinely rare, but the raw word must
 * never be shown to a user as if it were a real version string. */
function versionText(value: string): string {
  return value === "unknown" ? "Version unavailable" : value;
}

export default function About() {
  const build = useBuildInfo();
  const nativeInfo = useNativeAppInfo();
  const { status: notificationPermission } = useNotificationPermission();
  const pushDiagnostics = useNativePushDiagnostics();
  const legal = useLegalCompliance();
  const native = isNativeShell();

  return (
    <SettingsPage title="About MyKhaya">
      <div className="card-stack">
        <section className="card details about-version-card">
          <div className="about-brand-row">
            <Logo compact />
            <strong>MyKhaya</strong>
          </div>
          <dl>
            {native && nativeInfo && (
              <div>
                <dt>{nativePlatform() === "android" ? "Android app" : "iOS app"}</dt>
                <dd>
                  {versionText(nativeInfo.version)} (Build {nativeInfo.build})
                </dd>
              </div>
            )}
            <div>
              <dt>{native ? "Web" : "App version"}</dt>
              <dd>
                {build
                  ? native
                    ? versionText(build.version)
                    : `${versionText(build.version)} (Web)`
                  : "Loading…"}
              </dd>
            </div>
            {build?.channel === "development" && (
              <div>
                <dt>Environment</dt>
                <dd>Development</dd>
              </div>
            )}
          </dl>
        </section>

        {native && (
          <section className="card details">
            <h2>Notifications</h2>
            <dl>
              <div>
                <dt>Notification permission</dt>
                <dd>{PERMISSION_LABELS[notificationPermission] ?? "Unknown"}</dd>
              </div>
              {pushDiagnostics && (
                <>
                  <div>
                    <dt>Push registration</dt>
                    <dd>{pushDiagnostics.registered ? "Registered" : "Not registered"}</dd>
                  </div>
                  <div>
                    <dt>Push provider</dt>
                    <dd>{nativePlatform() === "android" ? "FCM" : "APNs"}</dd>
                  </div>
                  <div>
                    <dt>Device token</dt>
                    <dd>{pushDiagnostics.tokenPresent ? "Present" : "Not present"}</dd>
                  </div>
                  {pushDiagnostics.lastRegisteredAt && (
                    <div>
                      <dt>Last registration</dt>
                      <dd>{new Date(Number(pushDiagnostics.lastRegisteredAt)).toLocaleString()}</dd>
                    </div>
                  )}
                </>
              )}
            </dl>
          </section>
        )}

        <section className="card details legal-compliance-card">
          <div className="section-heading legal-compliance-heading">
            <span className="more-icon-tile sage" aria-hidden="true">
              <FileText size={20} strokeWidth={1.75} />
            </span>
            <div>
              <h2>Legal &amp; Compliance</h2>
              <p className="muted">View the legal documents that apply to your account.</p>
            </div>
          </div>
          {legal.error && (
            <p className="notice error" role="alert">
              {legal.error}
            </p>
          )}
          {legal.loading && !legal.error && (
            <p role="status" className="muted">
              Loading…
            </p>
          )}
          {!legal.loading && !legal.error && legal.rows.length === 0 && (
            <div className="legal-empty-state">
              <span className="more-icon-tile cream" aria-hidden="true">
                <FileText size={18} strokeWidth={1.75} />
              </span>
              <div>
                <h3>No legal documents published yet</h3>
                <p className="muted">
                  Your current legal documents will appear here when they become available.
                </p>
              </div>
            </div>
          )}
          {legal.rows.length > 0 && (
            <div className="more-group-rows legal-document-rows">
              {legal.rows.map((row) => {
                const Icon = LEGAL_ROW_ICON[row.documentKey] ?? FileText;
                return (
                  <Link
                    className="more-row more-row-with-status"
                    href={`/about/legal/${encodeURIComponent(row.documentKey)}`}
                    key={row.key}
                  >
                    <span className="more-icon-tile sage" aria-hidden="true">
                      <Icon size={20} strokeWidth={1.75} />
                    </span>
                    <span className="more-row-text">
                      <h2>{row.displayName}</h2>
                      <p>
                        Version {row.version}
                        <br />
                        {row.description}
                      </p>
                    </span>
                    <span className="more-row-status">
                      <span className="legal-status-pills">
                        {row.isTest && <span className="legal-status-pill test">TEST</span>}
                        <span className={`legal-status-pill ${row.presentation.tone}`}>
                          {row.presentation.tone === "satisfied" && "✓ "}
                          {row.presentation.label}
                        </span>
                      </span>
                      {row.presentation.dateLabel && (
                        <span className="legal-status-date">{row.presentation.dateLabel}</span>
                      )}
                    </span>
                    <span className="more-row-chevron" aria-hidden="true">
                      ›
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
          <div className="legal-info-panel">
            <Info size={18} aria-hidden="true" />
            <div>
              <h3>Keeping you informed</h3>
              <p>
                We may update these documents from time to time. If an update requires your
                attention, we&rsquo;ll ask you to review it when you next sign in.
              </p>
            </div>
          </div>
        </section>

        <div className="settings-list">
          <Link className="card" href="/service-status">
            <div>
              <h2>Service Status</h2>
              <p>Check whether MyKhaya is running normally</p>
            </div>
            <span>›</span>
          </Link>
        </div>
      </div>
    </SettingsPage>
  );
}
