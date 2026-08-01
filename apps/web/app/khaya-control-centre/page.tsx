import Link from "next/link";
import { KhayaControlShell } from "@/components/khaya-control-shell";

export default function KhayaControlCentre() {
  return (
    <KhayaControlShell
      title="Home administration"
      description="Manage the people, security and released modules for your Home."
    >
      <div className="control-card-grid">
        <Link className="card" href="/people">
          <h2>Members and roles</h2>
          <p>Relationships, invitations and household access.</p>
        </Link>
        <Link className="card" href="/khaya-control-centre/children">
          <h2>Child permissions</h2>
          <p>Guardians, age bands and privacy-conscious access.</p>
        </Link>
        <Link className="card" href="/khaya-control-centre/feature-management">
          <h2>Feature Management</h2>
          <p>Choose which released modules are available in this Home.</p>
        </Link>
        <Link className="card" href="/settings/security">
          <h2>Security</h2>
          <p>Review account and session protection.</p>
        </Link>
      </div>
    </KhayaControlShell>
  );
}
