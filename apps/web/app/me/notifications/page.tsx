"use client";

import { Bell, CalendarDays, ChevronRight, CircleAlert, ListChecks, Repeat, Settings2, UtensilsCrossed, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Notification } from "@mykhaya/shared-types";
import { AppShellContent } from "@/components/app-shell";
import { isSafeInternalPath } from "@/components/internal-path";
import { notificationRelativeTime } from "@/components/notification-tray";
import { useNotifications, type NotificationFilter } from "@/components/notification-state";

function notificationIcon(type: string) {
  if (type.includes("calendar") || type.includes("event")) return CalendarDays;
  if (type.includes("list")) return ListChecks;
  if (type.includes("meal")) return UtensilsCrossed;
  if (type.includes("member") || type.includes("family") || type.includes("invitation")) return Users;
  if (type.includes("nudge") || type.includes("routine")) return Repeat;
  return Bell;
}

function NotificationHistoryRow({
  notification,
  onSelect,
  onMarkRead,
  onClear,
}: {
  notification: Notification;
  onSelect: () => void;
  onMarkRead: () => void;
  onClear: () => void;
}) {
  const unread = !notification.read_at;
  const Icon = notificationIcon(notification.notification_type);
  return (
    <article className={`card notification-history-card${unread ? " unread" : ""}`}>
      <button type="button" className="notification-history-row" onClick={onSelect}>
        <span className="notification-history-icon" aria-hidden="true"><Icon size={19} /></span>
        <span className="notification-history-copy">
          <span className="notification-history-title">{notification.title}</span>
          <span className="notification-history-body">{notification.body}</span>
          <span className="notification-history-meta">
            <span>{notificationRelativeTime(notification.created_at)}</span>
            <span className="notification-history-state">{unread ? "Unread" : "Read"}</span>
          </span>
        </span>
        {isSafeInternalPath(notification.deep_link_path) ? <ChevronRight className="notification-history-chevron" size={19} aria-hidden="true" /> : null}
      </button>
      <div className="notification-history-actions">
        {unread ? <button type="button" className="tertiary" onClick={onMarkRead}>Mark as read</button> : null}
        <button type="button" className="tertiary" onClick={onClear}>Clear</button>
      </div>
    </article>
  );
}

export default function NotificationsPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<NotificationFilter>("all");
  const {
    unreadCount,
    historyNotifications,
    historyLoaded,
    historyHasMore,
    historyLoading,
    historyError,
    refreshNotificationHistory,
    loadMoreNotificationHistory,
    markRead,
    markAllRead,
    clearNotification,
    clearAllNotifications,
  } = useNotifications();

  useEffect(() => {
    void refreshNotificationHistory(filter);
  }, [filter, refreshNotificationHistory]);

  function selectNotification(notification: Notification) {
    if (!notification.read_at) void markRead(notification.id).catch(() => undefined);
    if (isSafeInternalPath(notification.deep_link_path)) router.push(notification.deep_link_path);
  }

  function clearAll() {
    if (window.confirm("Clear all notifications?")) void clearAllNotifications().catch(() => undefined);
  }

  const emptyMessage = filter === "unread" ? "No unread notifications." : "You’re all caught up.";

  return (
    <AppShellContent>
      <main className="standard-page module-page notification-centre-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow"><Bell size={14} aria-hidden="true" /> Notifications</p>
            <h1>Notifications</h1>
            <p className="muted">What’s happened in your MyKhaya home.</p>
          </div>
          <Link className="secondary notification-settings-link" href="/settings/notifications">
            <Settings2 size={16} aria-hidden="true" /> Notification settings
          </Link>
        </div>

        <div className="notification-centre-toolbar">
          <div className="rr-segmented notification-filter" role="tablist" aria-label="Notification filter">
            {(["all", "unread"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={filter === value}
                className={`rr-segment${filter === value ? " rr-segment-active" : ""}`}
                onClick={() => setFilter(value)}
              >
                {value === "all" ? "All" : "Unread"}
              </button>
            ))}
          </div>
          <div className="notification-centre-actions">
            {unreadCount ? <button type="button" className="secondary" onClick={() => void markAllRead().catch(() => undefined)}>Mark all read</button> : null}
            {historyNotifications.length > 0 ? <button type="button" className="tertiary" onClick={clearAll}>Clear notifications</button> : null}
          </div>
        </div>

        {historyError ? (
          <div className="notice error" role="alert">
            <CircleAlert size={16} aria-hidden="true" />
            <span>Unable to load notifications.</span>
            <button type="button" className="secondary" onClick={() => void refreshNotificationHistory(filter)}>Retry</button>
          </div>
        ) : null}
        {historyLoading && !historyLoaded ? <p className="notification-centre-status" role="status">Loading notifications…</p> : null}
        {!historyLoading && !historyError && historyLoaded && historyNotifications.length === 0 ? (
          <p className="empty-mini notification-centre-status">{emptyMessage}</p>
        ) : null}
        <div className="notification-history-list">
          {historyNotifications.map((notification) => (
            <NotificationHistoryRow
              key={notification.id}
              notification={notification}
              onSelect={() => selectNotification(notification)}
              onMarkRead={() => void markRead(notification.id).catch(() => undefined)}
              onClear={() => void clearNotification(notification.id)}
            />
          ))}
        </div>
        {historyHasMore ? (
          <button type="button" className="secondary notification-load-more" onClick={() => void loadMoreNotificationHistory()} disabled={historyLoading}>
            {historyLoading ? "Loading…" : "Load more"}
          </button>
        ) : null}
      </main>
    </AppShellContent>
  );
}
