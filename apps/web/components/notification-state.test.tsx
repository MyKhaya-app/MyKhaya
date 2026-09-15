// @vitest-environment jsdom
import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NotificationProvider, useNotifications } from "./notification-state";

const notification = {
  id: "n1",
  title: "Dinner reminder",
  body: "Pasta tonight",
  related_entity_type: null,
  related_entity_id: null,
  deep_link_path: "/meal-plans",
  read_at: null,
  created_at: "2026-09-15T10:00:00Z",
};

const apiMock = vi.hoisted(() => ({
  notificationUnreadCount: vi.fn(),
  notifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  clearNotification: vi.fn(),
  clearAllNotifications: vi.fn(),
}));

vi.mock("@mykhaya/api-client", () => ({ api: apiMock }));
vi.mock("./auth-provider", () => ({
  useAuth: () => ({ user: { id: "user-1" }, status: "ready" }),
}));
vi.mock("./native-runtime", () => ({ isNativeShell: () => false }));
vi.mock("@capacitor/app", () => ({
  App: { addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }) },
}));

function Consumer() {
  const state = useNotifications();
  return (
    <div>
      <output data-testid="count">{state.unreadCount ?? "loading"}</output>
      <output data-testid="recent">{state.recentNotifications.length}</output>
      <output data-testid="history">{state.historyNotifications.length}</output>
      <button onClick={() => void state.refreshRecentNotifications()}>load recent</button>
      <button onClick={() => void state.refreshNotificationHistory("unread")}>load history</button>
      <button onClick={() => void state.loadMoreNotificationHistory()}>load more history</button>
      <button onClick={() => void state.markRead("n1")}>mark read</button>
    </div>
  );
}

describe("NotificationProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.notificationUnreadCount.mockResolvedValue({ unread_count: 1 });
    apiMock.notifications.mockResolvedValue({ items: [notification], unread_count: 1, next_page: null });
    apiMock.markNotificationRead.mockResolvedValue({ message: "ok" });
  });

  it("loads only the unread count initially and loads recent history on demand", async () => {
    render(<NotificationProvider><Consumer /></NotificationProvider>);

    await waitFor(() => expect(screen.getByTestId("count")).toHaveTextContent("1"));
    expect(apiMock.notifications).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "load recent" }));
    await waitFor(() => expect(screen.getByTestId("recent")).toHaveTextContent("1"));
    expect(apiMock.notifications).toHaveBeenCalledWith({ filter: "all", limit: 8 });
  });

  it("optimistically marks a cached notification read and revalidates its count", async () => {
    render(<NotificationProvider><Consumer /></NotificationProvider>);
    fireEvent.click(screen.getByRole("button", { name: "load recent" }));

    await waitFor(() => expect(screen.getByTestId("recent")).toHaveTextContent("1"));
    fireEvent.click(screen.getByRole("button", { name: "mark read" }));

    await waitFor(() => expect(apiMock.markNotificationRead).toHaveBeenCalledWith("n1"));
    expect(apiMock.notificationUnreadCount).toHaveBeenCalledTimes(2);
  });

  it("loads paginated history independently from the tray cache", async () => {
    apiMock.notifications
      .mockResolvedValueOnce({ items: [notification], unread_count: 1, next_page: 2 })
      .mockResolvedValueOnce({ items: [notification], unread_count: 1, next_page: null });
    render(<NotificationProvider><Consumer /></NotificationProvider>);

    fireEvent.click(screen.getByRole("button", { name: "load history" }));
    await waitFor(() => expect(screen.getByTestId("history")).toHaveTextContent("1"));
    expect(apiMock.notifications).toHaveBeenCalledWith({ filter: "unread", page: 1, limit: 20 });

    fireEvent.click(screen.getByRole("button", { name: "load more history" }));
    await waitFor(() => expect(apiMock.notifications).toHaveBeenCalledWith({ filter: "unread", page: 2, limit: 20 }));
    expect(screen.getByTestId("history")).toHaveTextContent("1");
  });
});
