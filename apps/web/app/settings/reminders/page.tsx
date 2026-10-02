import { redirect } from "next/navigation";

// Routines and Reminders were consolidated into one "Routines & Reminders"
// module (see /settings/routines-reminders/page.tsx) — this route is kept
// as a permanent redirect rather than removed, so old bookmarks/deep links
// and any in-flight notification links pointing at /settings/reminders
// never 404.
export default function RemindersRedirect() {
  redirect("/settings/routines-reminders?type=reminders");
}
