import { redirect } from "next/navigation";

/** Superseded by the Notifications module (Templates sub-page), which
 *  covers everything this page did plus filtering, badges and reset-all.
 *  Kept as a redirect rather than deleted so old bookmarks/links keep
 *  working. Redirect target is a bare path, without a control-centre
 *  prefix — see middleware.ts's admin-host rewrite; a prefixed target here
 *  would get double-rewritten and 404 on the real admin domain. */
export default function NotificationTemplatesRedirectPage() {
  redirect("/notifications/templates");
}
