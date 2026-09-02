"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { CcConfirmDialog } from "@/components/control-centre/dialog";
import { titleCase } from "@/components/platform-format";

type ValueType = "text" | "email" | "url" | "boolean" | "integer" | "list";
type Risk = "normal" | "sensitive";
type RuntimeEffect = "effective" | "informational" | "not_enforced";
type SettingState = "configured" | "default" | "unset";

type SettingValue = string | number | boolean | string[] | null;

type SettingItem = {
  key: string;
  label: string;
  description: string;
  section: string;
  value_type: ValueType;
  risk: Risk;
  runtime_effect: RuntimeEffect;
  editable: boolean;
  consumer_visible: boolean;
  value: SettingValue;
  state: SettingState;
};

type EnvironmentItem = { key: string; value: string; category: string; editable: boolean };

type SettingsResponse = { settings: SettingItem[]; environment: EnvironmentItem[] };

// Sections render in this order regardless of API response order; any
// section not listed here (there shouldn't be one) falls back to the end.
const SECTION_ORDER = ["General", "Registration & Access", "Home Limits", "Support", "Regional", "Legal"];

function groupBySection(items: SettingItem[]): [string, SettingItem[]][] {
  const bySection = new Map<string, SettingItem[]>();
  for (const item of items) {
    const list = bySection.get(item.section) ?? [];
    list.push(item);
    bySection.set(item.section, list);
  }
  return [...bySection.entries()].sort(
    (a, b) => SECTION_ORDER.indexOf(a[0]) - SECTION_ORDER.indexOf(b[0]),
  );
}

function stateCaption(state: SettingState): string | null {
  if (state === "default") return "Using deployment default";
  if (state === "configured") return "Configured in Platform Control Centre";
  return null;
}

// Confirmation copy is derived from runtime_effect, never hand-written per
// key — a setting that later gains real enforcement only needs its schema
// runtime_effect changed to "effective" for this copy to switch to the
// stronger operational warning; see docs/architecture/platform-control-centre.md.
function confirmationDescription(item: SettingItem): string {
  if (item.runtime_effect === "not_enforced") {
    return (
      "This setting is not yet enforced by the application — saving it records the " +
      "configured value in Platform Control Centre but does not currently change user " +
      "access or behaviour."
    );
  }
  return `${item.label} affects real user access or availability. Make sure you intend this change before saving.`;
}

function toDraftText(value: SettingValue): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function parseDraft(valueType: ValueType, draft: string, boolDraft: boolean): SettingValue {
  if (valueType === "boolean") return boolDraft;
  if (valueType === "integer") return Number(draft);
  if (valueType === "list")
    return draft
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  return draft;
}

function isDirty(item: SettingItem, draft: string, boolDraft: boolean): boolean {
  if (item.value_type === "boolean") return Boolean(item.value) !== boolDraft;
  return toDraftText(item.value) !== draft;
}

function SettingRow({ item, onSaved }: { item: SettingItem; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(() => toDraftText(item.value));
  const [boolDraft, setBoolDraft] = useState(() => Boolean(item.value));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    setDraft(toDraftText(item.value));
    setBoolDraft(Boolean(item.value));
  }, [item.value]);

  const dirty = isDirty(item, draft, boolDraft);

  const save = useCallback(
    async (reasonText: string) => {
      setSaving(true);
      setError("");
      try {
        await platformApi.put(`/settings/${item.key}`, {
          value: parseDraft(item.value_type, draft, boolDraft),
          reason: reasonText,
          confirmed: true,
        });
        setReason("");
        await onSaved();
      } catch (cause) {
        setError((cause as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [item.key, item.value_type, draft, boolDraft, onSaved],
  );

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty || saving) return;
    if (item.risk === "sensitive") {
      setConfirmOpen(true);
      return;
    }
    void save(reason);
  }

  const caption = stateCaption(item.state);

  return (
    <div className="action-panel setting-row">
      <div className="setting-row-heading">
        <h2>{item.label}</h2>
        <small className="setting-row-key">{item.key}</small>
      </div>
      <p className="muted">{item.description}</p>
      {item.runtime_effect === "not_enforced" && (
        <p className="notice">Not yet enforced by the application.</p>
      )}
      <form className="setting-row-form" onSubmit={onSubmit}>
        {item.value_type === "boolean" ? (
          <label className="check-row">
            <input
              type="checkbox"
              checked={boolDraft}
              onChange={(event) => setBoolDraft(event.target.checked)}
            />
            Enabled
          </label>
        ) : (
          <input
            type={
              item.value_type === "email"
                ? "email"
                : item.value_type === "url"
                  ? "url"
                  : item.value_type === "integer"
                    ? "number"
                    : "text"
            }
            value={draft}
            placeholder={item.state === "unset" ? "Not yet set" : undefined}
            onChange={(event) => setDraft(event.target.value)}
          />
        )}
        {caption && <small className="setting-row-caption">{caption}</small>}
        {item.risk !== "sensitive" && (
          <label>
            Reason for this change
            <input
              type="text"
              value={reason}
              minLength={10}
              maxLength={500}
              required={dirty}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        )}
        <button type="submit" disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <CcConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={`Save ${item.label}?`}
        description={confirmationDescription(item)}
        confirmLabel="Save"
        variant="destructive"
        onConfirm={async (formData) => {
          const raw = formData.get("audit_reason");
          const confirmReason = typeof raw === "string" ? raw : "";
          setConfirmOpen(false);
          await save(confirmReason);
        }}
      />
    </div>
  );
}

export default function PlatformSettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await platformApi.get<SettingsResponse>("/settings"));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PlatformShell>
      <main className="platform-page">
        <div className="platform-heading">
          <div>
            <p>Control Centre</p>
            <h1>Settings</h1>
          </div>
        </div>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {!data && !error ? (
          <p role="status">Loading settings…</p>
        ) : (
          data && (
            <>
              <section className="overview-panel">
                <h2>Environment</h2>
                <p className="notice">Managed by the deployment environment — edit the server's .env and redeploy.</p>
                <dl>
                  {data.environment.map((item) => (
                    <div key={item.key}>
                      <dt>{titleCase(item.key)}</dt>
                      <dd>{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              {groupBySection(data.settings).map(([section, items]) => (
                <section key={section} className="platform-settings-section">
                  <h2>{section}</h2>
                  <div className="settings-section-rows">
                    {items.map((item) => (
                      <SettingRow key={item.key} item={item} onSaved={load} />
                    ))}
                  </div>
                </section>
              ))}
            </>
          )
        )}
      </main>
    </PlatformShell>
  );
}
