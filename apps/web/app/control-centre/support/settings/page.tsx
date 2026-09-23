"use client";

import { PlatformShell } from "@/components/platform-shell";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcSection, CcCard } from "@/components/control-centre/section";
import { CcEmptyState } from "@/components/control-centre/status-message";

// Phase 2B intentionally ships only the Tickets queue — support notification
// email, bug-report notification email, and the Support/Knowledge
// Base/Service Status enable-disable toggles mentioned in the Phase 1 audit
// are a later phase's work, not this one's. This page exists so the
// Support nav group's "Settings" link resolves to something explicit
// rather than a 404, matching the Knowledge Base "Coming soon" precedent
// on the consumer Help & Support hub.
export default function SupportSettingsPage() {
  return (
    <PlatformShell>
      <CcPage>
        <CcPageHeader
          eyebrow="Support"
          title="Support settings"
          description="Configuration for the Support ticket system."
        />
        <CcSection>
          <CcCard>
            <CcEmptyState>Coming soon.</CcEmptyState>
          </CcCard>
        </CcSection>
      </CcPage>
    </PlatformShell>
  );
}
