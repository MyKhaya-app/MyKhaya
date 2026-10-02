"use client";

import { App } from "@capacitor/app";
import type { Notification } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "./auth-provider";
import { isNativeShell } from "./native-runtime";

const RECENT_LIMIT = 8;
const HISTORY_LIMIT = 20;

export type NotificationFilter = "all" | "unread";

export type NotificationState = {
  unreadCount: number | null;
  recentNotifications: Notification[];
  recentLoaded: boolean;
  historyNotifications: Notification[];
  historyFilter: NotificationFilter;
  historyLoaded: boolean;
  historyPage: number;
  historyHasMore: boolean;
  historyLoading: boolean;
  historyError: string | null;
  loading: boolean;
  error: string | null;
  refreshUnreadCount: () => Promise<void>;
  refreshRecentNotifications: () => Promise<void>;
  refreshNotifications: () => Promise<void>;
  refreshNotificationHistory: (filter: NotificationFilter) => Promise<void>;
  loadMoreNotificationHistory: () => Promise<void>;
  markRead: (notificationId: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  clearNotification: (notificationId: string) => Promise<void>;
  clearAllNotifications: () => Promise<void>;
};

const NotificationStateContext = createContext<NotificationState | null>(null);

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Unable to load notifications.";
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { user, status } = useAuth();
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [recentNotifications, setRecentNotifications] = useState<Notification[]>([]);
  const [recentLoaded, setRecentLoaded] = useState(false);
  const [historyNotifications, setHistoryNotifications] = useState<Notification[]>([]);
  const [historyFilter, setHistoryFilter] = useState<NotificationFilter>("all");
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef({ unread: 0, recent: 0, history: 0 });
  const mutationVersion = useRef(0);
  const activeRequests = useRef(0);

  const setRequestLoading = useCallback((active: boolean) => {
    activeRequests.current += active ? 1 : -1;
    setLoading(activeRequests.current > 0);
  }, []);

  const refreshUnreadCount = useCallback(async () => {
    const sequence = ++requestSequence.current.unread;
    const mutationAtStart = mutationVersion.current;
    setRequestLoading(true);
    try {
      const result = await api.notificationUnreadCount();
      if (sequence === requestSequence.current.unread && mutationAtStart === mutationVersion.current) {
        setUnreadCount(result.unread_count);
        setError(null);
      }
    } catch (cause) {
      if (sequence === requestSequence.current.unread && mutationAtStart === mutationVersion.current) {
        setError(errorMessage(cause));
      }
    } finally {
      setRequestLoading(false);
    }
  }, [setRequestLoading]);

  const refreshRecentNotifications = useCallback(async () => {
    const sequence = ++requestSequence.current.recent;
    const mutationAtStart = mutationVersion.current;
    setRequestLoading(true);
    try {
      const result = await api.notifications({ filter: "all", limit: RECENT_LIMIT });
      if (sequence === requestSequence.current.recent && mutationAtStart === mutationVersion.current) {
        setRecentNotifications(result.items);
        setRecentLoaded(true);
        setError(null);
      }
    } catch (cause) {
      if (sequence === requestSequence.current.recent && mutationAtStart === mutationVersion.current) {
        setError(errorMessage(cause));
      }
    } finally {
      setRequestLoading(false);
    }
  }, [setRequestLoading]);

  const refreshNotifications = useCallback(async () => {
    await Promise.all([refreshUnreadCount(), refreshRecentNotifications()]);
  }, [refreshRecentNotifications, refreshUnreadCount]);

  const refreshNotificationHistory = useCallback(async (filter: NotificationFilter) => {
    const sequence = ++requestSequence.current.history;
    const mutationAtStart = mutationVersion.current;
    setHistoryFilter(filter);
    setHistoryNotifications([]);
    setHistoryPage(0);
    setHistoryHasMore(false);
    setHistoryLoaded(false);
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await api.notifications({ filter, page: 1, limit: HISTORY_LIMIT });
      if (sequence === requestSequence.current.history && mutationAtStart === mutationVersion.current) {
        setHistoryNotifications(result.items);
        setHistoryPage(1);
        setHistoryHasMore(result.next_page !== null);
        setHistoryLoaded(true);
      }
    } catch (cause) {
      if (sequence === requestSequence.current.history && mutationAtStart === mutationVersion.current) {
        setHistoryError(errorMessage(cause));
      }
    } finally {
      if (sequence === requestSequence.current.history) setHistoryLoading(false);
    }
  }, []);

  const loadMoreNotificationHistory = useCallback(async () => {
    if (historyLoading || !historyHasMore || !historyPage) return;
    const sequence = ++requestSequence.current.history;
    const mutationAtStart = mutationVersion.current;
    const nextPage = historyPage + 1;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await api.notifications({ filter: historyFilter, page: nextPage, limit: HISTORY_LIMIT });
      if (sequence === requestSequence.current.history && mutationAtStart === mutationVersion.current) {
        setHistoryNotifications((items) => {
          const existing = new Set(items.map((item) => item.id));
          return [...items, ...result.items.filter((item) => !existing.has(item.id))];
        });
        setHistoryPage(nextPage);
        setHistoryHasMore(result.next_page !== null);
      }
    } catch (cause) {
      if (sequence === requestSequence.current.history && mutationAtStart === mutationVersion.current) {
        setHistoryError(errorMessage(cause));
      }
    } finally {
      if (sequence === requestSequence.current.history) setHistoryLoading(false);
    }
  }, [historyFilter, historyHasMore, historyLoading, historyPage]);

  const mutate = useCallback(async (
    action: () => Promise<unknown>,
    optimistic: () => void,
    rollback: () => void,
  ) => {
    mutationVersion.current += 1;
    optimistic();
    setRequestLoading(true);
    try {
      await action();
      setError(null);
    } catch (cause) {
      rollback();
      setError(errorMessage(cause));
      throw cause;
    } finally {
      setRequestLoading(false);
    }
  }, [setRequestLoading]);

  const markRead = useCallback(async (notificationId: string) => {
    const previous = recentNotifications;
    const previousHistory = historyNotifications;
    const item = [...previous, ...previousHistory].find((notification) => notification.id === notificationId);
    const wasUnread = Boolean(item && !item.read_at);
    const now = new Date().toISOString();
    await mutate(
      () => api.markNotificationRead(notificationId),
      () => {
        setRecentNotifications((items) => items.map((notification) =>
          notification.id === notificationId ? { ...notification, read_at: notification.read_at ?? now } : notification,
        ));
        setHistoryNotifications((items) => historyFilter === "unread"
          ? items.filter((notification) => notification.id !== notificationId)
          : items.map((notification) =>
            notification.id === notificationId ? { ...notification, read_at: notification.read_at ?? now } : notification,
          ));
        if (wasUnread) setUnreadCount((count) => count === null ? count : Math.max(0, count - 1));
      },
      () => {
        setRecentNotifications(previous);
        setHistoryNotifications(previousHistory);
      },
    );
    await refreshUnreadCount();
    if (recentLoaded) await refreshRecentNotifications();
  }, [historyFilter, historyNotifications, mutate, recentLoaded, recentNotifications, refreshRecentNotifications, refreshUnreadCount]);

  const markAllRead = useCallback(async () => {
    const previous = recentNotifications;
    const previousHistory = historyNotifications;
    const now = new Date().toISOString();
    await mutate(
      () => api.markAllNotificationsRead(),
      () => {
        setUnreadCount(0);
        setRecentNotifications((items) => items.map((notification) => ({ ...notification, read_at: notification.read_at ?? now })));
        if (historyFilter === "unread") {
          setHistoryNotifications([]);
          setHistoryHasMore(false);
        } else {
          setHistoryNotifications((items) => items.map((notification) => ({ ...notification, read_at: notification.read_at ?? now })));
        }
      },
      () => {
        setRecentNotifications(previous);
        setHistoryNotifications(previousHistory);
      },
    );
    await refreshUnreadCount();
    if (recentLoaded) await refreshRecentNotifications();
  }, [historyFilter, historyNotifications, mutate, recentLoaded, recentNotifications, refreshRecentNotifications, refreshUnreadCount]);

  const clearNotification = useCallback(async (notificationId: string) => {
    const previous = recentNotifications;
    const previousHistory = historyNotifications;
    const item = [...previous, ...previousHistory].find((notification) => notification.id === notificationId);
    await mutate(
      () => api.clearNotification(notificationId),
      () => {
        setRecentNotifications((items) => items.filter((notification) => notification.id !== notificationId));
        setHistoryNotifications((items) => items.filter((notification) => notification.id !== notificationId));
        if (item && !item.read_at) setUnreadCount((count) => count === null ? count : Math.max(0, count - 1));
      },
      () => {
        setRecentNotifications(previous);
        setHistoryNotifications(previousHistory);
      },
    );
    await refreshUnreadCount();
    if (recentLoaded) await refreshRecentNotifications();
  }, [historyNotifications, mutate, recentLoaded, recentNotifications, refreshRecentNotifications, refreshUnreadCount]);

  const clearAllNotifications = useCallback(async () => {
    const previous = recentNotifications;
    const previousHistory = historyNotifications;
    await mutate(
      () => api.clearAllNotifications(),
      () => {
        setRecentNotifications([]);
        setHistoryNotifications([]);
        setUnreadCount(0);
      },
      () => {
        setRecentNotifications(previous);
        setHistoryNotifications(previousHistory);
      },
    );
    await refreshUnreadCount();
    if (recentLoaded) await refreshRecentNotifications();
  }, [historyNotifications, mutate, recentLoaded, recentNotifications, refreshRecentNotifications, refreshUnreadCount]);

  useEffect(() => {
    if (status !== "ready" || !user?.id) return;
    setUnreadCount(null);
    setRecentNotifications([]);
    setRecentLoaded(false);
    setHistoryNotifications([]);
    setHistoryLoaded(false);
    setHistoryPage(0);
    setHistoryHasMore(false);
    setHistoryError(null);
    setError(null);
    mutationVersion.current += 1;
    void refreshUnreadCount();
  }, [refreshUnreadCount, status, user?.id]);

  useEffect(() => {
    if (status !== "ready" || !user?.id) return;
    const refreshOnForeground = () => {
      if (document.visibilityState === "visible") {
        void refreshUnreadCount();
        if (recentLoaded) void refreshRecentNotifications();
      }
    };
    document.addEventListener("visibilitychange", refreshOnForeground);
    let disposed = false;
    let removeAppListener: (() => void) | undefined;
    if (isNativeShell()) {
      void App.addListener("appStateChange", ({ isActive }) => {
        if (!isActive) return;
        void refreshUnreadCount();
        if (recentLoaded) void refreshRecentNotifications();
      }).then((handle) => {
        if (disposed) void handle.remove();
        else removeAppListener = () => { void handle.remove(); };
      });
    }
    return () => {
      disposed = true;
      document.removeEventListener("visibilitychange", refreshOnForeground);
      removeAppListener?.();
    };
  }, [recentLoaded, refreshRecentNotifications, refreshUnreadCount, status, user?.id]);

  const value = useMemo(() => ({
    unreadCount, recentNotifications, recentLoaded,
    historyNotifications, historyFilter, historyLoaded, historyPage, historyHasMore, historyLoading, historyError,
    loading, error, refreshUnreadCount, refreshRecentNotifications, refreshNotifications,
    refreshNotificationHistory, loadMoreNotificationHistory,
    markRead, markAllRead, clearNotification, clearAllNotifications,
  }), [clearAllNotifications, clearNotification, error, historyError, historyFilter, historyHasMore, historyLoaded, historyLoading, historyNotifications, historyPage, loadMoreNotificationHistory, loading, markAllRead, markRead, recentLoaded, recentNotifications, refreshNotificationHistory, refreshNotifications, refreshRecentNotifications, refreshUnreadCount, unreadCount]);

  return <NotificationStateContext.Provider value={value}>{children}</NotificationStateContext.Provider>;
}

export function useNotifications() {
  const context = useContext(NotificationStateContext);
  if (!context) throw new Error("useNotifications must be used inside NotificationProvider");
  return context;
}
