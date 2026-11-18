// Test-only helper (never imported by app code). A module page registers its
// primary action with useConsumerPrimaryAction(); AppShell's
// ConsumerActionDock is what renders the button. Rendering a page on its own
// therefore has no Add button, so page tests render it the way AppShell does.
import type { ReactElement, ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { ConsumerActionDock, ConsumerActionProvider } from "./consumer-action-dock";

export function WithConsumerActions({ children }: { children: ReactNode }) {
  return (
    <ConsumerActionProvider>
      {children}
      <ConsumerActionDock />
    </ConsumerActionProvider>
  );
}

export function renderWithConsumerActions(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: WithConsumerActions, ...options });
}
