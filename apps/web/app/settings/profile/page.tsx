"use client";
import { useEffect, useState } from "react";
import type { User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
export default function Profile() {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    api.me().then(setUser);
  }, []);
  return (
    <SettingsPage title="Your profile">
      <section className="card details">
        <h2>Account details</h2>
        <dl>
          <div>
            <dt>Name</dt>
            <dd>{user?.display_name ?? "—"}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user?.email ?? "—"}</dd>
          </div>
          <div>
            <dt>Email status</dt>
            <dd>{user?.email_verified ? "Verified" : "Verification needed"}</dd>
          </div>
        </dl>
      </section>
    </SettingsPage>
  );
}
