"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, Shield } from "lucide-react";
import type { VehicleMot } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { motDateLine, motStatusLabel, motStatusTone, relativeTime } from "./mot-format";

// The vehicle's current MOT position, for UK vehicles only (the parent never
// renders this for other countries — no UI for features that don't apply).
// Reading uses persisted data; when that data is stale the card asks the
// server for an "if_stale" refresh once, and the server decides whether
// DVSA is actually contacted. The explicit Refresh button is the only
// user-triggered provider call.
export function MotCard({
  homeId,
  vehicleId,
  mot,
  onChange,
}: {
  homeId: string;
  vehicleId: string;
  mot: VehicleMot;
  onChange: (next: VehicleMot) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const autoChecked = useRef(false);
  const { summary } = mot;
  const canRefresh = mot.provider_available && mot.has_registration;

  useEffect(() => {
    if (autoChecked.current || !canRefresh || !summary.stale) return;
    autoChecked.current = true;
    api
      .refreshVehicleMot(homeId, vehicleId, "if_stale")
      .then(onChange)
      .catch(() => {
        // A background freshness check never interrupts the page; the
        // persisted data stays on screen and the user can refresh manually.
      });
  }, [canRefresh, summary.stale, homeId, vehicleId, onChange]);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const next = await api.refreshVehicleMot(homeId, vehicleId, "force");
      onChange(next);
      if (next.refresh?.message) setMessage(next.refresh.message);
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.message : "We couldn't check the MOT right now.");
    } finally {
      setBusy(false);
    }
  }

  const label = motStatusLabel(summary.status);
  const dateLine = motDateLine(summary);
  const checked = relativeTime(summary.refreshed_at);
  return (
    <section className="card driveway-mot-card" aria-labelledby="driveway-mot-heading">
      <div className="driveway-mot-heading">
        <Shield size={22} aria-hidden="true" />
        <h2 id="driveway-mot-heading">MOT</h2>
      </div>
      {label ? (
        <>
          <p className={`driveway-mot-status driveway-mot-status-${motStatusTone(summary.status)}`}>{label}</p>
          {dateLine && <p className="driveway-mot-date">{dateLine}</p>}
        </>
      ) : (
        <p className="muted">
          {!mot.has_registration
            ? "Add this vehicle's registration to check its MOT."
            : mot.provider_available
              ? "We haven't checked this vehicle's MOT yet."
              : "MOT checks aren't available right now."}
        </p>
      )}
      {checked && <p className="driveway-mot-checked muted">Last checked {checked}</p>}
      {canRefresh && (
        <button type="button" className="secondary" onClick={() => void refresh()} disabled={busy} aria-busy={busy}>
          <RefreshCw size={16} aria-hidden="true" /> {busy ? "Checking…" : label ? "Refresh" : "Check MOT"}
        </button>
      )}
      {message && <p className="driveway-mot-message" role="status">{message}</p>}
    </section>
  );
}
