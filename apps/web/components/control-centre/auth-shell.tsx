import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

/**
 * Shared outer chrome for the three pre-authentication PCC surfaces (login,
 * MFA enrollment, invitation acceptance) — deliberately NOT PlatformShell,
 * since none of these pages have an authenticated actor/session to render a
 * sidebar around. Reuses the existing `.platform-login`/`section` CSS
 * (already on the shared --cc-* token root — see app/styles.css) rather than
 * introducing a second auth visual theme; this component only adds the
 * brand mark and kicker markup that used to be hand-duplicated in each page.
 */
export function CcAuthShell({
  kicker = "Restricted management plane",
  children,
}: {
  kicker?: string | null;
  children?: ReactNode;
}) {
  return (
    <main className="pcc-root platform-login">
      <div className="tailadmin-auth-layout">
        <aside className="tailadmin-auth-art" aria-label="MyKhaya Platform Control Centre">
          <div className="tailadmin-auth-mark">MK</div>
          <strong>MyKhaya</strong>
          <span>Platform Control Centre</span>
          <p>Secure operational access for authorised platform administrators.</p>
        </aside>
        <section>
          <div className="cc-auth-brand">
            <span aria-hidden="true"><ShieldCheck size={20} strokeWidth={2} /></span>
            <div><strong>MyKhaya</strong><small>Platform Control Centre</small></div>
          </div>
          {kicker && <p className="platform-kicker">{kicker}</p>}
          {children}
        </section>
      </div>
    </main>
  );
}
