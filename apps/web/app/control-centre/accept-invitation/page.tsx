"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "@/components/platform-mfa-logic";
import { titleCase } from "@/components/platform-format";
import type { AdministratorInvitationPreview, PlatformActor } from "@/components/platform-types";
import { CcAuthShell } from "@/components/control-centre/auth-shell";
import { CcNotice, CcLoadingState } from "@/components/control-centre/status-message";
import { CcField } from "@/components/control-centre/form-field";
import { CcMetadataGrid, CcMetadataItem } from "@/components/control-centre/metadata-grid";
import { CcBadge } from "@/components/control-centre/badge";

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={<CcAuthShell kicker={null} />}>
      <AcceptInvitationForm />
    </Suspense>
  );
}

function AcceptInvitationForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [preview, setPreview] = useState<AdministratorInvitationPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("This invitation link is missing its token.");
      return;
    }
    platformApi
      .get<AdministratorInvitationPreview>(
        `/administrators/invitations/preview?token=${encodeURIComponent(token)}`,
      )
      .then(setPreview)
      .catch((cause) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : "This invitation is invalid or has expired.",
        ),
      );
  }, [token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const password = (data.get("password") as string | null) ?? "";
    const confirmPassword = (data.get("confirm_password") as string | null) ?? "";
    if (password !== confirmPassword) {
      setError("Those passwords do not match.");
      setBusy(false);
      return;
    }
    try {
      const actor = await platformApi.post<PlatformActor>("/administrators/invitations/accept", {
        token,
        password,
      });
      const destination = resolveLoginDestination(actor.session_status);
      if (destination === "home") router.replace("/");
      else if (destination === "setup-mfa") router.replace("/setup-mfa");
      else router.replace("/login");
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "This invitation could not be accepted.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (error && !preview) {
    return (
      <CcAuthShell>
        <h1>Invitation unavailable</h1>
        <CcNotice tone="error">{error}</CcNotice>
      </CcAuthShell>
    );
  }

  if (!preview) {
    return (
      <CcAuthShell>
        <CcLoadingState label="Checking your invitation…" />
      </CcAuthShell>
    );
  }

  return (
    <CcAuthShell>
      <h1>Set up your administrator account</h1>
      <p>
        {preview.invited_by_display_name ?? "An Owner"} invited you as{" "}
        <CcBadge tone="info">{titleCase(preview.role)}</CcBadge> for the MyKhaya Platform Control
        Centre — global administration access, separate from any Home. Choose a password to
        continue; you will be asked to set up multi-factor authentication next.
      </p>
      <CcMetadataGrid>
        <CcMetadataItem label="Name">{preview.display_name}</CcMetadataItem>
        <CcMetadataItem label="Email">{preview.email}</CcMetadataItem>
      </CcMetadataGrid>
      <form onSubmit={submit}>
        <CcField label="Password">
          <input name="password" type="password" autoComplete="new-password" required minLength={16} maxLength={128} />
        </CcField>
        <CcField label="Confirm password">
          <input name="confirm_password" type="password" autoComplete="new-password" required minLength={16} maxLength={128} />
        </CcField>
        {error && <CcNotice tone="error">{error}</CcNotice>}
        <button disabled={busy}>{busy ? "Setting up…" : "Set password and continue"}</button>
      </form>
      <small>
        This link is single-use and expires 24 hours after it was sent. If you were not expecting
        this, you can safely ignore it.
      </small>
    </CcAuthShell>
  );
}
