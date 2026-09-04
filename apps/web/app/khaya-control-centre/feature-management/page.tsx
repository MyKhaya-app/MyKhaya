"use client";

import { useEffect, useMemo, useState } from "react";
import type { FeatureKey, HouseholdModule } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { KhayaControlShell } from "@/components/khaya-control-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";

export default function FeatureManagementPage() {
  const { activeHomeId } = useActiveHome();
  const [modules, setModules] = useState<HouseholdModule[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (activeHomeId) setModules(await api.featureManagement(activeHomeId));
  }

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [activeHomeId]);

  const grouped = useMemo(
    () =>
      Object.entries(
        modules.reduce<Record<string, HouseholdModule[]>>((groups, module) => {
          (groups[module.category] ??= []).push(module);
          return groups;
        }, {}),
      ),
    [modules],
  );

  async function update(module: HouseholdModule) {
    if (!activeHomeId || busy) return;
    const enabled = !module.enabled;
    if (
      !window.confirm(
        `${enabled ? "Enable" : "Disable"} ${module.name} for this Home?`,
      )
    )
      return;
    setBusy(module.id);
    setError("");
    try {
      await api.updateHouseholdFeature(activeHomeId, module.id as FeatureKey, {
        enabled,
        confirmed: true,
      });
      setMessage(
        `${module.name} is now ${enabled ? "enabled" : "disabled"}. Existing data was preserved.`,
      );
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The feature could not be changed.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <KhayaControlShell
      title="Module management"
      description="Released modules can be enabled per Home. Unreleased modules remain completely hidden."
    >
      <FormStatus message={message} error={error} />
      {grouped.map(([category, entries]) => (
        <section
          key={category}
          className="feature-group"
          aria-labelledby={`category-${category}`}
        >
          <h2 id={`category-${category}`}>{category}</h2>
          <div className="feature-card-grid">
            {entries.map((module) => (
              <article className="card feature-card" key={module.id}>
                <div className="feature-card-heading">
                  <div>
                    <h3>{module.name}</h3>
                    <span className={`release-badge ${module.release_state}`}>
                      {module.release_state === "core"
                        ? "Core"
                        : module.release_state}
                    </span>
                  </div>
                  <strong>{module.enabled ? "Enabled" : "Disabled"}</strong>
                </div>
                <p>{module.description}</p>
                {module.dependencies.length > 0 && (
                  <small>
                    Requires:{" "}
                    {module.dependencies.join(", ").replaceAll("_", " ")}
                  </small>
                )}
                {module.introduced_version && (
                  <small>Introduced in {module.introduced_version}</small>
                )}
                {module.release_state === "beta" && (
                  <p className="beta-warning">
                    Beta modules may change and are disabled by default.
                  </p>
                )}
                {module.toggleable ? (
                  <button
                    type="button"
                    className={module.enabled ? "secondary" : ""}
                    disabled={busy !== null}
                    onClick={() => update(module)}
                    aria-pressed={module.enabled}
                  >
                    {busy === module.id
                      ? "Saving…"
                      : module.enabled
                        ? `Disable ${module.name}`
                        : `Enable ${module.name}`}
                  </button>
                ) : (
                  <p className="core-note">
                    Required for sign-in and Home administration.
                  </p>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}
    </KhayaControlShell>
  );
}
