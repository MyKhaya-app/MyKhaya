"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bell, ChevronDown, ChevronLeft } from "lucide-react";
import type { Vehicle, VehicleMot, VehicleMotTest } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { MotPill, RefreshButton, useMotRefresh } from "../../driveway-ui";
import {
  checkedAgo,
  formatMileage,
  formatPlate,
  formatShortDate,
  isFailureDefect,
  milesBetweenTests,
  motDaysText,
  motExpiryText,
  motNeedsAttention,
  motShortLabel,
  motState,
  vehicleName,
} from "../../vehicle-display";

// Driveway MOT history: status card, two stat tiles, and a newest-first
// timeline. Every value is the backend's normalised MOT data — no provider
// payloads or terminology.

function TimelineEntry({ test, latest, first }: { test: VehicleMotTest; latest: boolean; first: boolean }) {
  const [open, setOpen] = useState(latest);
  const mileage = formatMileage(test, true);
  const validUntil = test.result === "passed" && !first ? formatShortDate(test.expiry_date) : null;
  const detail = [mileage, validUntil ? `valid until ${validUntil}` : null, first ? "first MOT" : null].filter(Boolean).join(" · ");
  const bodyId = `drv-test-${test.id}`;
  return (
    <li className="drv-timeline-entry">
      <span className="drv-timeline-rail" aria-hidden="true">
        <span className={`drv-timeline-dot${latest ? " drv-timeline-dot-latest" : ""}`} />
        <span className="drv-timeline-line" />
      </span>
      <div className="drv-timeline-body">
        <div className="drv-test-top">
          <span className="drv-timeline-date">{formatShortDate(test.test_date)}</span>
          <span className={`drv-result drv-result-${test.result}`}>
            {test.result === "passed" ? "Passed" : test.result === "failed" ? "Failed" : "Result unavailable"}
          </span>
        </div>
        {detail && <span className="drv-timeline-meta">{detail}</span>}
        {open ? (
          <div id={bodyId} className="drv-timeline-detail">
            {test.defects.length === 0 ? (
              <span className="drv-pill drv-pill-valid drv-pill-small">No defects or advisories</span>
            ) : (
              <ul className="drv-defects">
                {test.defects.map((defect, index) => (
                  <li
                    key={`${test.id}-${index}`}
                    className={`drv-defect${defect.dangerous || isFailureDefect(defect.category) ? " drv-defect-fail" : ""}`}
                  >
                    {defect.dangerous && (
                      <span className="drv-defect-flag">
                        <AlertTriangle size={13} aria-hidden="true" /> Dangerous
                      </span>
                    )}
                    {defect.text}
                  </li>
                ))}
              </ul>
            )}
            {test.test_number && <span className="drv-muted-small">Test no. {test.test_number}</span>}
          </div>
        ) : (
          <button type="button" className="drv-show-more" aria-expanded={false} aria-controls={bodyId} onClick={() => setOpen(true)}>
            Show details <ChevronDown size={14} strokeWidth={2.4} aria-hidden="true" />
          </button>
        )}
      </div>
    </li>
  );
}

export default function VehicleMotHistoryPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId, activeHome } = useActiveHome();
  const { user } = useAuth();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [mot, setMot] = useState<VehicleMot | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeHomeId) return;
    setNotFound(false);
    Promise.all([api.vehicle(activeHomeId, vehicleId), api.vehicleMot(activeHomeId, vehicleId)])
      .then(([nextVehicle, nextMot]) => {
        setVehicle(nextVehicle);
        setMot(nextMot);
      })
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
        else setError(cause instanceof ApiError ? cause.message : "Could not load the MOT history.");
      });
  }, [activeHomeId, vehicleId]);

  const onMotChange = useCallback((next: VehicleMot) => setMot(next), []);
  const motRefresh = useMotRefresh(activeHomeId, vehicleId, mot, onMotChange);

  const name = vehicle ? vehicleName(vehicle) : "Vehicle";
  const back = (
    <Link className="drv-back" href={`/driveway/${vehicleId}?tab=mot`}>
      <ChevronLeft size={18} aria-hidden="true" /> {name}
    </Link>
  );

  if (notFound || (mot && !mot.eligible)) {
    return (
      <AppShellContent>
        <main className="standard-page module-page drv-page">
          {back}
          <p className="empty-mini">
            {notFound ? "That vehicle could not be found." : "MOT history is only available for vehicles registered in the UK."}
          </p>
        </main>
      </AppShellContent>
    );
  }

  const plate = formatPlate(vehicle?.registration);
  const state = mot ? motState(mot.summary.status, mot.summary.due_date) : motState(null, null);
  const checked = checkedAgo(mot?.summary.refreshed_at);
  const canNudge = Boolean(vehicle && (vehicle.owner_user_id === user?.id || activeHome?.relationship === "home_admin"));
  const tests = mot?.tests ?? [];
  const passed = tests.filter((test) => test.result === "passed").length;
  const between = milesBetweenTests(tests);

  return (
    <AppShellContent>
      <main className="standard-page module-page drv-page drv-history-page">
        {back}
        <div className="drv-heading-copy">
          <p className="drv-eyebrow">{plate ? `Vehicle · ${plate}` : "Vehicle"}</p>
          <h1 className="drv-title drv-title-section">MOT history</h1>
        </div>
        <FormStatus error={error} />
        {!activeHomeId || !mot ? (
          !error && <p role="status">Loading MOT history…</p>
        ) : (
          <div className="drv-history-layout">
            <div className="drv-history-side">
              <section className="drv-status-card" aria-label="Current MOT">
                <div className="drv-status-card-top">
                  <MotPill tone={state.tone} variant="onGreen">
                    {motShortLabel(state)}
                  </MotPill>
                  {motRefresh.canRefresh && <RefreshButton busy={motRefresh.busy} onClick={() => void motRefresh.refresh()} onGreen />}
                </div>
                {state.daysLeft !== null ? (
                  <div className="drv-status-card-copy">
                    <span className="drv-status-card-expiry">{motExpiryText(state)}</span>
                    <span className="drv-status-card-days">
                      {[motDaysText(state), checked ? `checked ${checked}` : null].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                ) : (
                  <span className="drv-status-card-days">We haven't got a current MOT date for this vehicle.</span>
                )}
                {motRefresh.message && (
                  <p className="drv-status-card-days" role="status">
                    {motRefresh.message}
                  </p>
                )}
                {canNudge && (
                  <Link
                    className={`drv-button drv-button-cream drv-button-compact-height${motNeedsAttention(state) ? " drv-button-attention" : ""}`}
                    href={`/driveway/${vehicleId}/mot/reminder?from=history`}
                  >
                    <Bell size={18} aria-hidden="true" /> Set MOT reminder
                  </Link>
                )}
              </section>
              {tests.length > 0 && (
                <section className="drv-stats" aria-label="MOT at a glance">
                  <div className="drv-stat">
                    <span className="drv-muted-small">Tests passed</span>
                    <strong>
                      {passed} of {tests.length}
                    </strong>
                  </div>
                  <div className="drv-stat">
                    <span className="drv-muted-small">Miles between tests</span>
                    <strong>{between !== null ? between.toLocaleString("en-GB") : "—"}</strong>
                  </div>
                </section>
              )}
            </div>
            {tests.length === 0 ? (
              <p className="empty-mini">No MOT tests recorded yet.</p>
            ) : (
              <ol className="drv-card drv-timeline" aria-label="MOT tests, newest first">
                {tests.map((test, index) => (
                  <TimelineEntry key={test.id} test={test} latest={index === 0} first={index === tests.length - 1} />
                ))}
              </ol>
            )}
          </div>
        )}
      </main>
    </AppShellContent>
  );
}
