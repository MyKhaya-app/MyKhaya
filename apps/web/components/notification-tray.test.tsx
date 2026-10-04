// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Notification } from "@mykhaya/shared-types";
import { NotificationBell, NotificationTray, notificationBadgeLabel } from "./notification-tray";

const state = vi.hoisted(() => ({
  unreadCount: 2,
  recentNotifications: [] as Notification[],
  recentLoaded: false,
  loading: false,
  error: null as string | null,
  refreshRecentNotifications: vi.fn().mockResolvedValue(undefined),
  markRead: vi.fn().mockResolvedValue(undefined),
  markAllRead: vi.fn().mockResolvedValue(undefined),
  clearAllNotifications: vi.fn().mockResolvedValue(undefined),
}));
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("./notification-state", () => ({ useNotifications: () => state }));
vi.mock("./bottom-sheet", () => ({
  BottomSheet: ({ title, headerAction, children, footer }: { title: string; headerAction?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode }) => (
    <div role="dialog" aria-label={title}>
      <h2>{title}</h2>
      {headerAction}
      {children}
      {footer}
    </div>
  ),
}));

const notification: Notification = {
  id: "n1",
  notification_type: "nudge",
  title: "A reminder",
  body: "Remember to check the list.",
  related_entity_type: null,
  related_entity_id: null,
  deep_link_path: "/lists",
  read_at: null,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  vi.clearAllMocks();
  state.unreadCount = 2;
  state.recentNotifications = [];
  state.recentLoaded = false;
  state.loading = false;
  state.error = null;
});

describe("notification controls", () => {
  it("uses hidden, numeric, and 9+ badge states", () => {
    expect(notificationBadgeLabel(0)).toBeNull();
    expect(notificationBadgeLabel(4)).toBe("4");
    expect(notificationBadgeLabel(10)).toBe("9+");
  });

  it("loads recent notifications lazily and safely navigates a selected row", async () => {
    state.recentLoaded = true;
    state.recentNotifications = [notification];
    const onDismiss = vi.fn();
    render(<NotificationTray onDismiss={onDismiss} />);

    await userEvent.setup().click(screen.getByRole("button", { name: /a reminder/i }));
    expect(state.markRead).toHaveBeenCalledWith("n1");
    expect(onDismiss).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/lists");
  });

  it("supports mark all read and confirmed clear actions", async () => {
    state.recentLoaded = true;
    state.recentNotifications = [notification];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<NotificationTray onDismiss={vi.fn()} />);
    const typist = userEvent.setup();
    await typist.click(screen.getByRole("button", { name: /mark all read/i }));
    await typist.click(screen.getByRole("button", { name: /clear notifications/i }));
    expect(state.markAllRead).toHaveBeenCalledTimes(1);
    expect(state.clearAllNotifications).toHaveBeenCalledTimes(1);
  });

  it("requests recent notifications when the tray opens", async () => {
    render(<NotificationTray onDismiss={vi.fn()} />);
    await waitFor(() => expect(state.refreshRecentNotifications).toHaveBeenCalledTimes(1));
  });

  it("exposes the unread count on the accessible bell label", () => {
    render(<NotificationBell onOpen={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Notifications, 2 unread" })).toBeInTheDocument();
  });

  it("links the tray to the full Notification Centre", () => {
    state.recentLoaded = true;
    render(<NotificationTray onDismiss={vi.fn()} />);
    expect(screen.getByRole("link", { name: "View all notifications" })).toHaveAttribute("href", "/me/notifications");
  });
});
