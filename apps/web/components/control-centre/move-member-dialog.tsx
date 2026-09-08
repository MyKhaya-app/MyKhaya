"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { useReauthGuard } from "@/components/platform-reauth-modal";
import { CcDialog, CcDialogActions } from "./dialog";
import { CcField } from "./form-field";
import { CcNotice } from "./status-message";

export type MoveMemberSourceHome = { id: string; name: string; role: string };

type HomeSearchResult = {
  id: string;
  name: string;
  active: boolean;
  member_count: number;
};

type MoveHomeResponse = {
  source_disposition: "left_unchanged" | "archived_empty";
};

const RELATIONSHIP_OPTIONS = [
  { value: "home_admin", label: "Home Admin" },
  { value: "partner", label: "Partner" },
  { value: "adult", label: "Adult" },
] as const;

type Relationship = (typeof RELATIONSHIP_OPTIONS)[number]["value"];
type SourceDisposition = "leave" | "archive_if_empty";

/**
 * PCC "Move member" — transfers a user's active membership from one Home to
 * another (see mykhaya.routers.platform.move_member). This is a membership
 * transfer only: it never touches the user's account, credentials, sessions,
 * or the source Home's calendars/lists/routines/data, so the impact summary
 * below spells that out before the operator confirms.
 *
 * Shared between the PCC user-detail page (source Home is one of the user's
 * current memberships, picked from `sourceHomes`) and, if ever wired up
 * there too, a Home-detail "Members" panel (source Home fixed to that Home).
 */
export function MoveMemberDialog({
  open,
  onClose,
  userId,
  userDisplayName,
  userEmail,
  sourceHomes,
  onMoved,
}: {
  open: boolean;
  onClose: () => void;
  userId: string;
  userDisplayName: string;
  userEmail: string;
  sourceHomes: MoveMemberSourceHome[];
  onMoved: (message: string) => void;
}) {
  const [sourceGroupId, setSourceGroupId] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HomeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [destinationGroupId, setDestinationGroupId] = useState("");
  const [destinationName, setDestinationName] = useState("");
  const [relationship, setRelationship] = useState<Relationship>("partner");
  const [disposition, setDisposition] = useState<SourceDisposition>("leave");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { guarded, modal: reauthModal } = useReauthGuard();
  const searchFieldId = useId();

  useEffect(() => {
    if (!open) return;
    setSourceGroupId(sourceHomes[0]?.id ?? "");
    setQuery("");
    setResults([]);
    setDestinationGroupId("");
    setDestinationName("");
    setRelationship("partner");
    setDisposition("leave");
    setReason("");
    setError("");
  }, [open, sourceHomes]);

  // Homes the user is already an active member of are never valid move
  // destinations — the backend rejects these too, but filtering them out of
  // search results here avoids an operator picking one only to be bounced.
  const excludedHomeIds = useMemo(() => new Set(sourceHomes.map((home) => home.id)), [sourceHomes]);

  const sourceHome = sourceHomes.find((home) => home.id === sourceGroupId);

  async function search() {
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearching(true);
    setError("");
    try {
      const page = await platformApi.get<{ items: HomeSearchResult[] }>(
        `/homes?q=${encodeURIComponent(trimmed)}&active=true&page_size=10`,
      );
      setResults(page.items.filter((home) => !excludedHomeIds.has(home.id)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unable to search Homes.");
    } finally {
      setSearching(false);
    }
  }

  const canSubmit = Boolean(
    sourceGroupId && destinationGroupId && reason.trim().length >= 10 && !busy,
  );

  // move-home is require_recent_auth()-gated server-side (same as the other
  // sensitive user actions on this page) — guarded() shows the reauth modal
  // and retries on a 403, mirroring the runAction pattern on the user-detail
  // page itself, kept local to this dialog so it's self-contained wherever
  // it's mounted.
  const submit = guarded(async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      const result = await platformApi.post<MoveHomeResponse>(
        `/users/${encodeURIComponent(userId)}/move-home`,
        {
          source_group_id: sourceGroupId,
          destination_group_id: destinationGroupId,
          destination_relationship: relationship,
          source_disposition: disposition,
          reason,
          confirmed: true,
        },
      );
      const dispositionNote =
        result.source_disposition === "archived_empty"
          ? ` ${sourceHome?.name ?? "The source Home"} had no members left and was archived.`
          : "";
      onMoved(`${userDisplayName} moved to ${destinationName}.${dispositionNote}`);
      onClose();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) throw cause;
      setError(cause instanceof ApiError ? cause.message : "Unable to move this member.");
    } finally {
      setBusy(false);
    }
  });

  return (
    <>
    <CcDialog open={open} onClose={onClose} title="Move member">
      <div className="cc-dialog-form">
        <div className="cc-dialog-scroll">
          {error && <CcNotice tone="error">{error}</CcNotice>}

          {sourceHomes.length > 1 ? (
            <CcField label="From Home">
              <select value={sourceGroupId} onChange={(event) => setSourceGroupId(event.target.value)}>
                {sourceHomes.map((home) => (
                  <option key={home.id} value={home.id}>
                    {home.name} ({home.role.replaceAll("_", " ")})
                  </option>
                ))}
              </select>
            </CcField>
          ) : (
            <p>
              Moving from <strong>{sourceHome?.name ?? "this Home"}</strong>.
            </p>
          )}

          <div className="cc-field">
            <label htmlFor={searchFieldId}>Find destination Home</label>
            <p className="cc-field-help">Search active Homes by name.</p>
            <div className="cc-move-member-search">
              <input
                id={searchFieldId}
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Home name"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void search();
                  }
                }}
              />
              <button type="button" className="secondary" onClick={() => void search()} disabled={searching}>
                {searching ? "Searching…" : "Search"}
              </button>
            </div>
          </div>

          {results.length > 0 && (
            <ul className="cc-move-member-results">
              {results.map((home) => (
                <li key={home.id}>
                  <button
                    type="button"
                    aria-pressed={home.id === destinationGroupId}
                    className={home.id === destinationGroupId ? "cc-move-member-result-selected" : undefined}
                    onClick={() => {
                      setDestinationGroupId(home.id);
                      setDestinationName(home.name);
                    }}
                  >
                    {home.name} — {home.member_count} member{home.member_count === 1 ? "" : "s"}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <CcField label="New relationship in destination Home">
            <select
              value={relationship}
              onChange={(event) => setRelationship(event.target.value as Relationship)}
            >
              {RELATIONSHIP_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </CcField>

          <fieldset className="cc-move-member-disposition">
            <legend>Source Home, once this member leaves</legend>
            <label>
              <input
                type="radio"
                name="source_disposition"
                checked={disposition === "leave"}
                onChange={() => setDisposition("leave")}
              />
              Leave unchanged
            </label>
            <label>
              <input
                type="radio"
                name="source_disposition"
                checked={disposition === "archive_if_empty"}
                onChange={() => setDisposition("archive_if_empty")}
              />
              Archive the source Home if this leaves it with no active members
            </label>
          </fieldset>

          {destinationGroupId && sourceHome && (
            <div className="cc-move-member-summary">
              <h3>Before you confirm</h3>
              <p>
                Moving <strong>{userDisplayName}</strong> ({userEmail}) from{" "}
                <strong>{sourceHome.name}</strong> to <strong>{destinationName}</strong> as{" "}
                {RELATIONSHIP_OPTIONS.find((option) => option.value === relationship)?.label}.
              </p>
              <ul>
                <li>Same account, same user ID, and login credentials — the account is never recreated.</li>
                <li>
                  Passkeys, trusted devices, native push registrations, notification preferences and
                  account settings all carry over unchanged.
                </li>
                <li>Their verified-email state is unaffected.</li>
                <li>
                  {sourceHome.name}&rsquo;s calendars, lists, routines, reminders and other Home data stay
                  with {sourceHome.name} — this moves membership only, never Home data.
                </li>
              </ul>
            </div>
          )}

          <CcField label="Reason for this administrative action (at least 10 characters)">
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
              minLength={10}
              maxLength={500}
            />
          </CcField>
        </div>
        <CcDialogActions>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" onClick={() => void submit()} disabled={!canSubmit}>
            {busy ? "Moving…" : "Move member"}
          </button>
        </CcDialogActions>
      </div>
    </CcDialog>
    {reauthModal}
    </>
  );
}
