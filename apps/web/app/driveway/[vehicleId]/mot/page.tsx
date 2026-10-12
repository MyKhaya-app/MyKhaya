"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { AlertTriangle, ChevronLeft } from "lucide-react";
import type { Vehicle, VehicleMot, VehicleMotTest } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { MotCard } from "../../mot-card";
import { formatLongDate, formatMileage, groupDefects, motResultLabel } from "../../mot-format";

// Driveway MOT history (Phase 1): one stacked card per test, newest first.
// Every value shown is the backend's normalised MOT data — no provider
// payloads or terminology. Stacked cards and disclosure panels rather than
// a wide table, per the mobile standards.

function MotTestCard({ test, open }: { test: VehicleMotTest; open: boolean }) {
  const groups = groupDefects(test.defects);
  const date = formatLongDate(test.test_date);
  const expiry = formatLongDate(test.expiry_date);
  const mileage = formatMileage(test);
  const tone = test.result === "passed" ? "good" : test.result === "failed" ? "warning" : "neutral";
  return (
    <li className="card driveway-mot-test">
      <details open={open}>
        <summary>
          <span className={`driveway-mot-result driveway-mot-status-${tone}`}>{motResultLabel(test.result)}</span>
          <span className="driveway-mot-test-date">{date}</span>
          {mileage && <span className="driveway-mot-test-meta muted">{mileage}</span>}
        </summary>
        <div className="driveway-mot-test-body">
          {expiry && test.result === "passed" && <p>Valid until {expiry}</p>}
          {groups.length === 0 ? (
            <p className="muted">No defects or advisories recorded.</p>
          ) : (
            groups.map((group) => (
              <section key={group.key} className="driveway-mot-defects">
                <h3>{group.title}</h3>
                <ul>
                  {group.items.map((defect, index) => (
                    <li key={`${group.key}-${index}`}>
                      {defect.dangerous && (
                        <span className="driveway-mot-dangerous">
                          <AlertTriangle size={14} aria-hidden="true" /> Dangerous
                        </span>
                      )}
                      {defect.text}
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
          {test.test_number && <p className="driveway-mot-test-number muted">Test number {test.test_number}</p>}
        </div>
      </details>
    </li>
  );
}

export default function VehicleMotHistoryPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
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

  const back = (
    <Link className="tertiary" href={`/driveway/${vehicleId}`}>
      <ChevronLeft size={16} aria-hidden="true" /> {vehicle?.nickname ?? "Vehicle"}
    </Link>
  );

  if (notFound || (mot && !mot.eligible)) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          {back}
          <p className="empty-mini">
            {notFound ? "That vehicle could not be found." : "MOT history is only available for vehicles registered in the UK."}
          </p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page module-page driveway-mot-page">
        {back}
        <div className="page-heading">
          <div>
            <p className="eyebrow">Vehicle</p>
            <h1>MOT history</h1>
            {vehicle && <p className="muted">{vehicle.nickname}</p>}
          </div>
        </div>
        <FormStatus error={error} />
        {!activeHomeId || !mot ? (
          !error && <p role="status">Loading MOT history…</p>
        ) : (
          <>
            <MotCard homeId={activeHomeId} vehicleId={vehicleId} mot={mot} onChange={setMot} />
            {mot.tests.length === 0 ? (
              <p className="empty-mini">No MOT tests recorded yet.</p>
            ) : (
              <ol className="driveway-mot-tests" aria-label="MOT tests, newest first">
                {mot.tests.map((test, index) => (
                  <MotTestCard key={test.id} test={test} open={index === 0} />
                ))}
              </ol>
            )}
          </>
        )}
      </main>
    </AppShellContent>
  );
}
