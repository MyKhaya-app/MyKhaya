import { redirect } from "next/navigation";

/** Superseded by the Notifications module (Templates sub-page), which
 *  covers everything this page did plus filtering, badges and reset-all.
 *  Kept as a redirect rather than deleted so old bookmarks/links keep
 *  working. */
export default function NotificationTemplatesRedirectPage() {
  redirect("/control-centre/notifications/templates");
}
