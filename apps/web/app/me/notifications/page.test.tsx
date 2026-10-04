// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Notification } from "@mykhaya/shared-types";
import NotificationsPage from "./page";

const push = vi.fn();
const state = vi.hoisted(() => ({
  unreadCount: 2,
  historyNotifications: [] as Notification[],
  historyLoaded: false,
  historyHasMore: false,
  historyLoading: false,
  historyError: null as string | null,
  refreshNotificationHistory: vi.fn().mockResolvedValue(undefined),
  loadMoreNotificationHistory: vi.fn().mockResolvedValue(undefined),
  markRead: vi.fn().mockResolvedValue(undefined),
  markAllRead: vi.fn().mockResolvedValue(undefined),
  clearNotification: vi.fn().mockResolvedValue(undefined),
  clearAllNotifications: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/notification-state", () => ({ useNotifications: () => state }));

const item: Notification = {
  id: "n1",
  notification_type: "calendar_event",
  title: "Calendar reminder",
  body: "The school event starts soon.",
  related_entity_type: "event",
  related_entity_id: "e1",
  deep_link_path: "/calendar",
  read_at: null,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  vi.clearAllMocks();
  state.unreadCount = 2;
  state.historyNotifications = [];
  state.historyLoaded = false;
  state.historyHasMore = false;
  state.historyLoading = false;
  state.historyError = null;
});

describe("Notification Centre", () => {
  it("loads the all filter and supports switching to unread", async () => {
    state.historyLoaded = true;
    render(<NotificationsPage />);
    await waitFor(() => expect(state.refreshNotificationHistory).toHaveBeenCalledWith("all"));
    await userEvent.setup().click(screen.getByRole("tab", { name: "Unread" }));
    await waitFor(() => expect(state.refreshNotificationHistory).toHaveBeenCalledWith("unread"));
  });

  it("marks a selected unread item read and navigates safely", async () => {
    state.historyLoaded = true;
    state.historyNotifications = [item];
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /calendar reminder/i }));
    expect(state.markRead).toHaveBeenCalledWith("n1");
    expect(push).toHaveBeenCalledWith("/calendar");
  });

  it("supports individual and page-level actions", async () => {
    state.historyLoaded = true;
    state.historyNotifications = [item];
    state.historyHasMore = true;
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<NotificationsPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark as read" }));
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await user.click(screen.getByRole("button", { name: "Mark all read" }));
    await user.click(screen.getByRole("button", { name: "Clear notifications" }));
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(state.markRead).toHaveBeenCalledWith("n1");
    expect(state.clearNotification).toHaveBeenCalledWith("n1");
    expect(state.markAllRead).toHaveBeenCalledTimes(1);
    expect(state.clearAllNotifications).toHaveBeenCalledTimes(1);
    expect(state.loadMoreNotificationHistory).toHaveBeenCalledTimes(1);
  });

  it("shows the empty state", () => {
    state.historyLoaded = true;
    render(<NotificationsPage />);
    expect(screen.getByText("You’re all caught up.")).toBeInTheDocument();
  });
});
