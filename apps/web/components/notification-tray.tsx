"use client";

import { Bell, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { Notification } from "@mykhaya/shared-types";
import { BottomSheet } from "./bottom-sheet";
import { isSafeInternalPath } from "./internal-path";
import { useNotifications } from "./notification-state";

export function notificationBadgeLabel(count: number | null) {
  if (!count) return null;
  return count > 9 ? "9+" : String(count);
}

export function notificationRelativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "Just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  if (hours < 48) return "Yesterday";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(timestamp);
}

function NotificationRow({ notification, onSelect }: { notification: Notification; onSelect: () => void }) {
  const unread = !notification.read_at;
  return (
    <li className={`notification-tray-row${unread ? " unread" : ""}`}>
      <button type="button" onClick={onSelect}>
        <span className="notification-tray-icon" aria-hidden="true">
          {unread ? <Bell size={18} /> : <Check size={18} />}
        </span>
        <span className="notification-tray-copy">
          <span className="notification-tray-title">{notification.title}</span>
          <span className="notification-tray-body">{notification.body}</span>
        </span>
        <span className="notification-tray-time">{notificationRelativeTime(notification.created_at)}</span>
      </button>
    </li>
  );
}

export function NotificationBell({ onOpen }: { onOpen: () => void }) {
  const { unreadCount } = useNotifications();
  const badge = notificationBadgeLabel(unreadCount);
  const label = badge ? `Notifications, ${badge} unread` : "Notifications";
  return (
    <button
      type="button"
      className="app-header-notifications"
      onClick={onOpen}
      aria-label={label}
      aria-haspopup="dialog"
    >
      <Bell size={20} aria-hidden="true" />
      {badge ? <span className="notification-badge" aria-hidden="true">{badge}</span> : null}
    </button>
  );
}

export function NotificationTray({ onDismiss }: { onDismiss: () => void }) {
  const router = useRouter();
  const {
    unreadCount,
    recentNotifications,
    recentLoaded,
    loading,
    error,
    refreshRecentNotifications,
    markRead,
    markAllRead,
    clearAllNotifications,
  } = useNotifications();

  useEffect(() => {
    if (!recentLoaded && !loading && !error) void refreshRecentNotifications();
  }, [error, loading, recentLoaded, refreshRecentNotifications]);

  function selectNotification(notification: Notification) {
    if (!notification.read_at) void markRead(notification.id).catch(() => undefined);
    onDismiss();
    if (isSafeInternalPath(notification.deep_link_path)) router.push(notification.deep_link_path);
  }

  const clearAll = () => {
    if (window.confirm("Clear all notifications?")) void clearAllNotifications().catch(() => undefined);
  };

  return (
    <BottomSheet
      title="Notifications"
      onDismiss={onDismiss}
      headerAction={
            <button type="button" className="notification-tray-mark-all" onClick={() => void markAllRead().catch(() => undefined)} disabled={!unreadCount}>
          Mark all read
        </button>
      }
      footer={
        <div className="notification-tray-footer-actions">
          <Link className="tertiary" href="/me/notifications" onClick={onDismiss}>View all notifications</Link>
          <button type="button" className="secondary notification-tray-clear" onClick={clearAll}>Clear notifications</button>
        </div>
      }
    >
      <div className="notification-tray">
        {loading && !recentLoaded ? <p className="muted notification-tray-status">Loading notifications…</p> : null}
        {error ? (
          <div className="notification-tray-status" role="alert">
            <p>Unable to load notifications.</p>
            <button type="button" className="secondary" onClick={() => void refreshRecentNotifications()}>Retry</button>
          </div>
        ) : null}
        {!loading && !error && recentLoaded && recentNotifications.length === 0 ? (
          <p className="muted notification-tray-status">You’re all caught up.</p>
        ) : null}
        {recentNotifications.length > 0 ? (
          <ul className="notification-tray-list">
            {recentNotifications.map((notification) => (
              <NotificationRow key={notification.id} notification={notification} onSelect={() => selectNotification(notification)} />
            ))}
          </ul>
        ) : null}
      </div>
    </BottomSheet>
  );
}
