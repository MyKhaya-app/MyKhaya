package app.mykhaya.mobile;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;

/**
 * Creates the fixed set of Android notification channels this app posts
 * FCM notifications into (mykhaya.notifications.push.send_fcm on the
 * backend chooses one of these three ids per notification_type — see that
 * module's own channel-strategy comment and
 * docs/architecture/notification-engine.md). A channel must exist on-device
 * before Android will show any notification targeting it; an unrecognised
 * channel_id silently drops the notification rather than falling back to a
 * default, so these ids must stay in sync with the backend's own constants
 * (FCM_CHANNEL_GENERAL/FCM_CHANNEL_REMINDERS/FCM_CHANNEL_CALENDAR_FAMILY).
 *
 * Deliberately a small, meaningful set — General / Reminders & Nudges /
 * Calendar & Family — rather than one channel per notification_type, so
 * Android's own Settings > Notifications screen stays legible.
 *
 * Channel creation is idempotent and safe to call on every app start
 * (createNotificationChannel() is a no-op for an id that already exists,
 * and never changes a user's own importance/sound overrides for it).
 */
final class NotificationChannels {

    private NotificationChannels() {}

    static void createAll(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;

        NotificationChannel general = new NotificationChannel(
                "general", "General", NotificationManager.IMPORTANCE_DEFAULT);
        general.setDescription("Account, security, and other MyKhaya notifications.");
        manager.createNotificationChannel(general);

        NotificationChannel reminders = new NotificationChannel(
                "reminders", "Reminders & Nudges", NotificationManager.IMPORTANCE_DEFAULT);
        reminders.setDescription("Event reminders, routines, birthdays, and daily nudge summaries.");
        manager.createNotificationChannel(reminders);

        NotificationChannel calendarFamily = new NotificationChannel(
                "calendar_family", "Calendar & Family", NotificationManager.IMPORTANCE_DEFAULT);
        calendarFamily.setDescription("Calendar invitations, changes, shared lists, and wishlist activity.");
        manager.createNotificationChannel(calendarFamily);
    }
}
