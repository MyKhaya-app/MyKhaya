"use client";

import { FormEvent, useEffect, useState } from "react";
import type { ChildAgeBand, ChildProfile, Member } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { KhayaControlShell } from "@/components/khaya-control-shell";
import { useActiveHome } from "@/components/use-active-home";

const permissionLabels: Record<string, string> = {
  calendar_view: "View the household calendar",
  calendar_create: "Add calendar events",
  calendar_edit_own: "Edit their own events",
  view_other_members_events: "View other members’ events",
  tasks_access: "Access tasks",
  shopping_access: "Access shopping lists",
  shopping_add: "Add shopping items",
  photo_upload: "Upload photos",
  selected_albums_view: "View selected albums",
  chat_access: "Use family chat when released",
  push_notifications: "Receive push notifications",
  location_share: "Share location when released",
  location_view_others: "See other members’ locations when released",
  wish_lists_access: "Use wish lists",
  selected_documents_view: "View selected documents",
  external_sharing: "Share content outside the Home",
};

const ageLabels: Record<ChildAgeBand, string> = {
  under_13: "Under 13",
  "13_to_15": "13 to 15",
  "16_to_17": "16 to 17",
};

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

export default function ChildrenPage() {
  const { activeHomeId } = useActiveHome();
  const [children, setChildren] = useState<ChildProfile[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const guardians = members.filter((member) =>
    ["home_admin", "partner"].includes(member.relationship),
  );

  async function load() {
    if (!activeHomeId) return;
    const [childRows, memberRows] = await Promise.all([
      api.children(activeHomeId),
      api.members(activeHomeId),
    ]);
    setChildren(childRows);
    setMembers(memberRows);
  }

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [activeHomeId]);

  async function createChild(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || busy) return;
    const data = new FormData(event.currentTarget);
    const guardianIds = data.getAll("guardians").map(String);
    if (!guardianIds.length) {
      setError("Choose at least one responsible adult.");
      return;
    }
    setBusy(true);
    try {
      await api.createChild(activeHomeId, {
        display_name: formText(data, "display_name"),
        age_band: formText(data, "age_band") as ChildAgeBand,
        guardian_membership_ids: guardianIds,
      });
      event.currentTarget.reset();
      setMessage("Child profile created with restrictive defaults.");
      setError("");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The Child profile could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function togglePermission(child: ChildProfile, key: string) {
    if (!activeHomeId) return;
    const next = { ...child.permissions, [key]: !child.permissions[key] };
    if (
      !window.confirm(
        `Save this child permission change for ${child.display_name}?`,
      )
    )
      return;
    try {
      await api.updateChildPermissions(activeHomeId, child.membership_id, {
        permissions: next,
        confirmed: true,
      });
      setMessage("Child permissions updated and active sessions revoked.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The child permission could not be changed.",
      );
    }
  }

  async function requestTransition(child: ChildProfile) {
    if (!activeHomeId) return;
    if (
      !window.confirm(
        "Start a review without granting any adult permissions automatically?",
      )
    )
      return;
    try {
      await api.requestChildAdultReview(activeHomeId, child.membership_id, {
        confirmed: true,
      });
      setMessage("Adult transition review recorded. No permissions changed.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The transition review could not be started.",
      );
    }
  }

  async function changeAgeBand(child: ChildProfile, ageBand: ChildAgeBand) {
    if (!activeHomeId || ageBand === child.age_band) return;
    if (
      !window.confirm(
        `Change ${child.display_name}'s age band to ${ageLabels[ageBand]}?`,
      )
    )
      return;
    try {
      await api.updateChildAgeBand(activeHomeId, child.membership_id, {
        age_band: ageBand,
        confirmed: true,
      });
      setMessage("Age band updated and audited.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The age band could not be changed.",
      );
    }
  }

  async function updateGuardians(
    event: FormEvent<HTMLFormElement>,
    child: ChildProfile,
  ) {
    event.preventDefault();
    if (!activeHomeId) return;
    const guardianIds = new FormData(event.currentTarget)
      .getAll("guardians")
      .map(String);
    if (!guardianIds.length) {
      setError("Choose at least one responsible adult.");
      return;
    }
    if (
      !window.confirm(
        `Save the guardian assignments for ${child.display_name}?`,
      )
    )
      return;
    try {
      await api.updateChildGuardians(activeHomeId, child.membership_id, {
        guardian_membership_ids: guardianIds,
        confirmed: true,
      });
      setMessage("Responsible adults updated and audited.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Guardians could not be changed.",
      );
    }
  }

  async function saveBirthday(
    event: FormEvent<HTMLFormElement>,
    child: ChildProfile,
  ) {
    event.preventDefault();
    if (!activeHomeId) return;
    const data = new FormData(event.currentTarget);
    const month = data.get("birth_month");
    const day = data.get("birth_day");
    try {
      await api.updateChildBirthday(activeHomeId, child.membership_id, {
        birth_month: month ? Number(month) : null,
        birth_day: day ? Number(day) : null,
        birthday_visible: data.get("birthday_visible") === "on",
        confirmed: true,
      });
      setMessage("Birthday updated.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The birthday could not be changed.",
      );
    }
  }

  async function anonymise(child: ChildProfile) {
    if (!activeHomeId) return;
    if (
      !window.confirm(
        `Anonymise ${child.display_name}? This removes access and identifying profile data.`,
      )
    )
      return;
    try {
      await api.anonymiseChild(activeHomeId, child.membership_id, {
        confirmed: true,
      });
      setMessage("Child profile anonymised and access removed.");
      await load();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The profile could not be anonymised.",
      );
    }
  }

  return (
    <KhayaControlShell
      title="Child accounts"
      description="Managed profiles use data minimisation, explicit guardians and the safest available defaults."
    >
      <section className="card child-setup">
        <h2>Create a managed Child profile</h2>
        <p>No full date of birth or adult sign-in invitation is required.</p>
        <form onSubmit={createChild}>
          <label>
            Display name
            <input
              name="display_name"
              required
              maxLength={100}
              autoComplete="off"
            />
          </label>
          <label>
            Age band
            <select name="age_band" defaultValue="under_13">
              <option value="under_13">Under 13</option>
              <option value="13_to_15">13 to 15</option>
              <option value="16_to_17">16 to 17</option>
            </select>
          </label>
          <fieldset>
            <legend>Responsible adults</legend>
            {guardians.map((guardian) => (
              <label className="check-row" key={guardian.user_id}>
                <input
                  name="guardians"
                  type="checkbox"
                  value={guardian.membership_id}
                />
                {guardian.display_name} ·{" "}
                {guardian.relationship === "home_admin"
                  ? "Home Admin"
                  : "Partner"}
              </label>
            ))}
          </fieldset>
          <p className="notice">
            A responsible adult is recorded explicitly. MyKhaya does not assume
            every administrator is a guardian.
          </p>
          <button disabled={busy}>
            {busy ? "Creating…" : "Create Child profile"}
          </button>
        </form>
      </section>

      <FormStatus message={message} error={error} />

      <div className="child-list">
        {children.map((child) => (
          <article className="card child-card" key={child.membership_id}>
            <header>
              <div>
                <h2>{child.display_name}</h2>
                <p>
                  {ageLabels[child.age_band]} ·{" "}
                  {child.guardian_membership_ids.length} guardian
                  {child.guardian_membership_ids.length === 1 ? "" : "s"}
                </p>
              </div>
              <span
                className={`release-badge ${child.transition_status === "review_due" ? "beta" : "core"}`}
              >
                {child.transition_status === "review_due"
                  ? "Adult review due"
                  : "Managed Child"}
              </span>
            </header>
            <label>
              Age band
              <select
                value={child.age_band}
                onChange={(event) =>
                  changeAgeBand(child, event.target.value as ChildAgeBand)
                }
              >
                {Object.entries(ageLabels).map(([value, label]) => (
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <details>
              <summary>Responsible adults</summary>
              <form onSubmit={(event) => updateGuardians(event, child)}>
                {guardians.map((guardian) => (
                  <label className="check-row" key={guardian.membership_id}>
                    <input
                      name="guardians"
                      type="checkbox"
                      value={guardian.membership_id}
                      defaultChecked={child.guardian_membership_ids.includes(
                        guardian.membership_id,
                      )}
                    />
                    {guardian.display_name}
                  </label>
                ))}
                <button type="submit" className="secondary">
                  Save responsible adults
                </button>
              </form>
            </details>
            <details>
              <summary>Birthday</summary>
              <form onSubmit={(event) => saveBirthday(event, child)}>
                <label>
                  Month
                  <select name="birth_month" defaultValue={child.birth_month ?? ""}>
                    <option value="">Not set</option>
                    {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => (
                      <option key={month} value={month}>
                        {month}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Day
                  <input
                    type="number"
                    name="birth_day"
                    min={1}
                    max={31}
                    defaultValue={child.birth_day ?? ""}
                  />
                </label>
                <label className="check-row">
                  <input
                    type="checkbox"
                    name="birthday_visible"
                    defaultChecked={child.birthday_visible}
                  />{" "}
                  Show this birthday to the household (off by default)
                </label>
                <button type="submit" className="secondary">
                  Save birthday
                </button>
              </form>
            </details>
            <details>
              <summary>Child permissions</summary>
              <div className="permission-list">
                {Object.entries(permissionLabels).map(([key, label]) => (
                  <label className="permission-row" key={key}>
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      checked={child.permissions[key] === true}
                      onChange={() => togglePermission(child, key)}
                    />
                  </label>
                ))}
              </div>
            </details>
            <button
              className="secondary"
              type="button"
              onClick={() => requestTransition(child)}
            >
              Start adult transition review
            </button>
            <button
              className="danger-link"
              type="button"
              onClick={() => anonymise(child)}
            >
              Anonymise and remove Child profile
            </button>
          </article>
        ))}
        {!children.length && (
          <p className="hint">No managed Child profiles in this Home.</p>
        )}
      </div>
    </KhayaControlShell>
  );
}
