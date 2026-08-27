import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

const { ServiceWorkerRegister } = await import("./service-worker-register");

function stubServiceWorker() {
  const listeners: Record<string, (event: MessageEvent) => void> = {};
  vi.stubGlobal("navigator", {
    serviceWorker: {
      register: vi.fn().mockResolvedValue({ update: vi.fn() }),
      addEventListener: (type: string, listener: (event: MessageEvent) => void) => {
        listeners[type] = listener;
      },
      removeEventListener: vi.fn(),
    },
  });
  return {
    dispatch(data: unknown) {
      listeners.message?.({ data } as MessageEvent);
    },
  };
}

beforeEach(() => {
  push.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ServiceWorkerRegister — foreground notification-click navigation", () => {
  it("navigates through the router when a valid internal path arrives", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "mykhaya-notification-click", path: "/calendar?event=abc" });

    expect(push).toHaveBeenCalledWith("/calendar?event=abc");
  });

  it("ignores a message that isn't the expected shape", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "some-other-message", path: "/calendar" });
    sw.dispatch({ path: "/calendar" });
    sw.dispatch("not even an object");

    expect(push).not.toHaveBeenCalled();
  });

  it("rejects a protocol-relative path", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "mykhaya-notification-click", path: "//evil.example/phish" });

    expect(push).not.toHaveBeenCalled();
  });

  it("rejects a javascript: URL smuggled after a leading slash", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "mykhaya-notification-click", path: "/javascript:alert(1)" });

    expect(push).not.toHaveBeenCalled();
  });

  it("rejects a fully external https URL", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "mykhaya-notification-click", path: "https://evil.example/phish" });

    expect(push).not.toHaveBeenCalled();
  });

  it("rejects a path that isn't a string at all", () => {
    const sw = stubServiceWorker();
    render(<ServiceWorkerRegister />);

    sw.dispatch({ type: "mykhaya-notification-click", path: { toString: () => "/home" } });

    expect(push).not.toHaveBeenCalled();
  });
});
