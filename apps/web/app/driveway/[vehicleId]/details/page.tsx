"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, use, useEffect, useRef, useState } from "react";
import { ChevronLeft } from "lucide-react";
import type { Member, Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { FormActions, FormLayout } from "@/components/form-layout";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import {
  dateInputUnreadable,
  useFocusFirstInvalid,
  vehicleFieldErrors,
  VehicleFields,
  type VehicleFieldErrors,
  type VehicleFieldValues,
} from "../../vehicle-fields";

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That vehicle could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function VehicleDetailsEditPage({
  params,
}: {
  params: Promise<{ vehicleId: string }>;
}) {
  const { vehicleId } = use(params);
  const router = useRouter();
  const { activeHomeId, activeHome } = useActiveHome();
  const { user } = useAuth();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [values, setValues] = useState<VehicleFieldValues>({
    countryCode: "GB",
    registration: "",
    ownerUserId: "",
    nickname: "",
    make: "",
    model: "",
    year: "",
    fuelType: "",
    colour: "",
    firstRegistrationDate: "",
    engineSize: "",
    vin: "",
  });
  const [members, setMembers] = useState<Member[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<VehicleFieldErrors>({});
  const [failedAttempts, setFailedAttempts] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  useFocusFirstInvalid(formRef, failedAttempts);

  const update = (patch: Partial<VehicleFieldValues>) => {
    setValues((current) => ({ ...current, ...patch }));
    setFieldErrors((current) => {
      const next = { ...current };
      for (const key of Object.keys(patch)) delete next[key as keyof VehicleFieldErrors];
      return next;
    });
  };

  useEffect(() => {
    if (!activeHomeId) return;
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
    setNotFound(false);
    api
      .vehicle(activeHomeId, vehicleId)
      .then((row) => {
        setVehicle(row);
        setValues({
          ownerUserId: row.owner_user_id,
          countryCode: row.country_code,
          registration: row.registration ?? "",
          nickname: row.nickname,
          make: row.make ?? "",
          model: row.model ?? "",
          year: row.year ? String(row.year) : "",
          fuelType: row.fuel_type ?? "",
          colour: row.colour ?? "",
          firstRegistrationDate: row.first_registration_date ?? "",
          engineSize: row.engine_size ?? "",
          vin: row.vin ?? "",
        });
      })
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
        else setLoadError(loadErrorMessage(cause, "Could not load this vehicle."));
      });
  }, [activeHomeId, vehicleId]);

  // A viewer who isn't this vehicle's own owner or a home_admin never
  // receives its VIN from the API (see routers.driveway) — the field is
  // left out of the form entirely for them rather than rendered blank,
  // which would otherwise look like (and risk becoming) clearing it.
  const canSeeVin =
    !!vehicle && !!user && (vehicle.owner_user_id === user.id || activeHome?.relationship === "home_admin");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || !vehicle || busy) return;
    const errors = vehicleFieldErrors(values, {
      requireNickname: true,
      firstRegistrationDateUnreadable: dateInputUnreadable(event.currentTarget, "first_registration_date"),
    });
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError("");
      setFailedAttempts((count) => count + 1);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.updateVehicle(activeHomeId, vehicle.id, {
        nickname: values.nickname.trim(),
        owner_user_id: values.ownerUserId,
        country_code: values.countryCode,
        registration: values.registration.trim(),
        make: values.make.trim() || null,
        model: values.model.trim() || null,
        colour: values.colour.trim() || null,
        year: values.year ? Number(values.year) : null,
        fuel_type: values.fuelType || null,
        engine_size: values.engineSize.trim() || null,
        first_registration_date: values.firstRegistrationDate || null,
        vin: canSeeVin ? values.vin.trim() || null : null,
        expected_updated_at: vehicle.updated_at,
      });
      router.push(`/driveway/${vehicle.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save these changes.");
    } finally {
      setBusy(false);
    }
  }

  if (notFound) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          <Link className="tertiary" href="/driveway">
            <ChevronLeft size={16} aria-hidden="true" /> Driveway
          </Link>
          <p className="empty-mini">That vehicle could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!activeHomeId || !vehicle) {
    return (
      <AppShellContent>
        <main className="standard-page module-page">
          <p role="status">Loading vehicle…</p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page module-page">
        <Link className="tertiary" href={`/driveway/${vehicle.id}`}>
          <ChevronLeft size={16} aria-hidden="true" /> {vehicle.nickname}
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Vehicle details</p>
            <h1>{vehicle.nickname}</h1>
          </div>
        </div>
        <FormStatus error={loadError} />

        <FormLayout className="card details vehicle-form" onSubmit={submit} ref={formRef}>
          <VehicleFields
            values={values}
            onChange={update}
            errors={fieldErrors}
            members={members}
            currentUserId={user?.id}
            showVin={canSeeVin}
            nicknameRequired
          />
          {error && <p className="notice error" role="alert">{error}</p>}
          <FormActions>
            <button className="button" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </button>
          </FormActions>
        </FormLayout>
      </main>
    </AppShellContent>
  );
}
