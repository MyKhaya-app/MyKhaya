"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, Plus } from "lucide-react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import type {
  ManagedDemoHome,
  ManagedDemoHomeCreateRequest,
  ManagedDemoTemplate,
  ManagedDemoType,
} from "@/components/platform-types";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcField } from "@/components/control-centre/form-field";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { validateManagedDemoPassword, MANAGED_DEMO_PASSWORD_MIN_LENGTH } from "./password-validation";
import {
  ACCESS_LABELS,
  DEFAULT_TEMPLATE,
  FALLBACK_TEMPLATES,
  TEMPLATE_LABELS,
  isTemplateList,
  todayIso,
} from "./templates";
const safeError = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;

const statusTone: Record<ManagedDemoHome["status"], CcBadgeTone> = {
  enabled: "success",
  disabled: "neutral",
  expired: "danger",
};
const statusLabel: Record<ManagedDemoHome["status"], string> = {
  enabled: "Enabled",
  disabled: "Disabled",
  expired: "Expired",
};

export default function DemoTestHomesPage() {
  const router = useRouter();
  const [rows, setRows] = useState<ManagedDemoHome[] | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [templates, setTemplates] = useState<ManagedDemoTemplate[]>(FALLBACK_TEMPLATES);
  const [fixtureType, setFixtureType] = useState<ManagedDemoType>("apple_review");
  const [populate, setPopulate] = useState(true);
  const [pinDates, setPinDates] = useState(false);
  const [referenceDate, setReferenceDate] = useState(todayIso);
  const { guarded, modal } = useReauthGuard();
  const template = templates.find((row) => row.fixture_type === fixtureType) ?? DEFAULT_TEMPLATE;

  const load = async () => {
    try {
      setRows(await platformApi.get<ManagedDemoHome[]>("/demo-test-homes"));
      setError("");
    } catch (error) {
      setError(safeError(error, "Unable to load managed Demo/Test Homes."));
    }
  };
  useEffect(() => {
    void load();
    // The template catalogue describes which modules each plan's showcase
    // populates; the form falls back to the static list if it is unavailable.
    platformApi
      .get<unknown>("/demo-test-homes/templates")
      .then((value) => {
        if (isTemplateList(value) && value.length > 0) setTemplates(value);
      })
      .catch(() => undefined);
  }, []);

  function chooseTemplate(value: ManagedDemoType) {
    setFixtureType(value);
    setPopulate(true);
    setPinDates(false);
  }

  // POST /demo-test-homes enforces require_recent_auth() server-side
  // (apps/api/mykhaya/routers/platform.py), so a 403 here needs to trigger
  // the same reauth-and-retry flow other Control Centre mutations use.
  const submitCreate = guarded(async (request: ManagedDemoHomeCreateRequest) => {
    setBusy(true);
    try {
      const created = await platformApi.post<ManagedDemoHome>("/demo-test-homes", request);
      setPassword("");
      setConfirm("");
      router.push(`/demo-test-homes/${created.id}`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setFormError(safeError(cause, "Unable to create the managed Home. Check the details and try again."));
    } finally {
      setBusy(false);
    }
  });

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    const validationError = validateManagedDemoPassword(password, confirm);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    const data = new FormData(event.currentTarget);
    const field = (name: string) => {
      const value = data.get(name);
      return typeof value === "string" ? value : "";
    };
    if (template.showcase && populate && pinDates && !referenceDate) {
      setFormError("Choose a reference date, or switch off pinned dates.");
      return;
    }
    const request: ManagedDemoHomeCreateRequest = {
      fixture_key: field("fixture_key"),
      display_name: field("display_name"),
      fixture_type: fixtureType,
      email: field("email"),
      password,
      expires_at: field("expires_at") ? new Date(field("expires_at")).toISOString() : null,
      enabled: data.get("enabled") === "on",
      ...(template.showcase
        ? {
            populate_showcase: populate,
            showcase_reference_date: populate && pinDates ? referenceDate : null,
          }
        : {}),
    };
    await submitCreate(request);
  }

  const columns: CcTableColumn<ManagedDemoHome>[] = [
    {
      key: "home",
      header: "Home",
      render: (row) => (
        <>
          <a href={`/demo-test-homes/${row.id}`}>{row.display_name}</a>
          <br />
          <small>{row.fixture_key}</small>
        </>
      ),
    },
    { key: "template", header: "Template", render: (row) => TEMPLATE_LABELS[row.fixture_type] },
    { key: "account", header: "Account", render: (row) => row.account_email },
    {
      key: "status",
      header: "Status",
      render: (row) => <CcBadge tone={statusTone[row.status]}>{statusLabel[row.status]}</CcBadge>,
    },
    {
      key: "verification",
      header: "Verification",
      render: (row) => (
        <CcBadge tone={row.email_verified ? "success" : "warning"}>
          {row.email_verified ? "Verified" : "Unverified"}
        </CcBadge>
      ),
    },
    {
      key: "access",
      header: "Plan access",
      render: (row) => <CcBadge tone="info">{ACCESS_LABELS[row.access]}</CcBadge>,
    },
    {
      key: "refreshed",
      header: "Last refreshed",
      render: (row) => (row.refreshed_at ? new Date(row.refreshed_at).toLocaleString() : "Never"),
    },
    {
      key: "expiry",
      header: "Expiry",
      render: (row) => (row.expires_at ? new Date(row.expires_at).toLocaleString() : "No expiry"),
    },
    {
      key: "view",
      header: "",
      render: (row) => (
        <button className="secondary" onClick={() => router.push(`/demo-test-homes/${row.id}`)}>
          <Eye aria-hidden size={16} strokeWidth={2} /> View
        </button>
      ),
    },
  ];

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="Operations"
          title="Demo & Test Homes"
          description="Managed accounts used for App Store review, store screenshots, sales demos and QA — provisioned as pre-verified fixtures, separate from real customer Homes."
          primaryAction={
            <button onClick={() => setOpen((value) => !value)}>
              <Plus aria-hidden size={16} strokeWidth={2} /> Create Demo/Test Home
            </button>
          }
        />
        {error && <CcNotice tone="error">{error}</CcNotice>}

        {open && (
          <CcSection title="Create Demo/Test Home">
            <CcCard>
              <p>
                Demo/Test accounts created here are provisioned as verified managed accounts and do not
                require email verification.
              </p>
              <form onSubmit={create}>
                <CcField label="Template">
                  <select
                    name="fixture_type"
                    value={fixtureType}
                    onChange={(event) => chooseTemplate(event.target.value as ManagedDemoType)}
                  >
                    {templates.map((row) => (
                      <option key={row.fixture_type} value={row.fixture_type}>
                        {row.label}
                      </option>
                    ))}
                  </select>
                </CcField>
                {template.showcase && (
                  <div className="cc-showcase-options">
                    <CcNotice tone="info">
                      {populate ? (
                        <>
                          Populates a fictional household — Emma, James, Sophie and Oliver Parker — with
                          realistic, current-dated content for screenshots and product demos. Emma is the
                          sign-in account. Uses genuine {ACCESS_LABELS[template.access]} access with no
                          payment.
                          {template.showcase_modules.length > 0 && (
                            <>
                              {" "}
                              <strong>Populated:</strong>{" "}
                              {template.showcase_modules.map((module) => module.name).join(", ")}.
                            </>
                          )}
                        </>
                      ) : (
                        <>
                          Creates a clean Home with genuine {ACCESS_LABELS[template.access]} access and no
                          sample content, for engineering test scenarios.
                        </>
                      )}
                    </CcNotice>
                    <label>
                      <input
                        name="populate_showcase"
                        type="checkbox"
                        checked={populate}
                        onChange={(event) => setPopulate(event.target.checked)}
                      />{" "}
                      Populate with showcase data
                    </label>
                    {populate && (
                      <>
                        <label>
                          <input
                            name="pin_dates"
                            type="checkbox"
                            checked={pinDates}
                            onChange={(event) => setPinDates(event.target.checked)}
                          />{" "}
                          Pin dates to a reference date (screenshot mode)
                        </label>
                        {pinDates ? (
                          <CcField
                            label="Reference date"
                            help="Content is laid out around this day, so repeated resets give identical screenshots."
                          >
                            <input
                              name="showcase_reference_date"
                              type="date"
                              value={referenceDate}
                              onChange={(event) => setReferenceDate(event.target.value)}
                              required
                            />
                          </CcField>
                        ) : (
                          <small>Dates roll from today, so the current week and month always look active.</small>
                        )}
                      </>
                    )}
                  </div>
                )}
                <CcField label="Fixture key">
                  <input name="fixture_key" required pattern="[a-z0-9][a-z0-9-]+" />
                </CcField>
                <CcField label="Home name">
                  <input name="display_name" required />
                </CcField>
                <CcField label="Account email">
                  <input name="email" type="email" required />
                </CcField>
                <CcField label="New password">
                  <input
                    name="password"
                    type="password"
                    autoComplete="new-password"
                    minLength={MANAGED_DEMO_PASSWORD_MIN_LENGTH}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                </CcField>
                <CcField label="Confirm password">
                  <input
                    name="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    minLength={MANAGED_DEMO_PASSWORD_MIN_LENGTH}
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    required
                  />
                </CcField>
                <CcField label="Expiry" help="Optional. Leave blank for no expiry.">
                  <input name="expires_at" type="datetime-local" />
                </CcField>
                <label>
                  <input name="enabled" type="checkbox" defaultChecked /> Enabled
                </label>
                {formError && <CcNotice tone="error">{formError}</CcNotice>}
                <div className="platform-modal-actions" style={{ justifyContent: "flex-start" }}>
                  <button disabled={busy}>{busy ? "Creating…" : "Create"}</button>
                  <button type="button" className="secondary" onClick={() => setOpen(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            </CcCard>
          </CcSection>
        )}

        <CcSection
          title="Managed Homes"
          actions={
            <button className="secondary" onClick={() => void load()}>
              Refresh list
            </button>
          }
        >
          <CcTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            emptyMessage="No managed Demo/Test Homes."
            caption="Managed Demo/Test Homes"
          />
        </CcSection>
      </CcPage>

      {modal}
    </PlatformShell>
  );
}
