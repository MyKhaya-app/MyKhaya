// Browser entry for scripts/form-layout-harness.mjs: renders real form and
// sheet components, chosen by location.hash, so the harness can measure their
// rendered geometry in Chromium with the real design tokens and styles.css.
// Never imported by the app.

import { createRoot } from "react-dom/client";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { CopyEventSheet } from "../app/calendar/copy-event-sheet";
import { BottomSheet, syncSheetToVisualViewport } from "../components/bottom-sheet";
import { FormField, FormLayout, FormRow, FormSection, FormSheet } from "../components/form-layout";

const timedEvent = {
  event_id: "fixture-event",
  title: "Swimming lesson with a deliberately long title that wraps",
  start_at: "2030-11-04T15:00:00Z",
  end_at: "2030-11-04T16:30:00Z",
  timezone: "Europe/London",
  is_all_day: false,
} as unknown as EventOccurrence;

function noop() {}

function PrimitivesFixture() {
  return (
    <FormSheet title="Form layout primitives" onDismiss={noop} primaryAction={<button type="button">Save</button>}>
      <FormLayout>
        <FormSection title="Two columns with long labels">
          <FormRow>
            <FormField label="A deliberately long label that has to wrap onto several lines" hint="Help text that is also long enough to wrap across the column.">
              {(control) => <input {...control} type="text" defaultValue="A value" />}
            </FormField>
            <FormField label="Amount" error="Enter an amount greater than zero, using numbers only.">
              {(control) => <input {...control} type="number" defaultValue="0" />}
            </FormField>
          </FormRow>
        </FormSection>
        <FormSection title="Three columns" framed>
          <FormRow columns={3}>
            <FormField label="Date">{(control) => <input {...control} type="date" defaultValue="2030-11-05" />}</FormField>
            <FormField label="Start">{(control) => <input {...control} type="time" defaultValue="09:00" />}</FormField>
            <FormField label="End">{(control) => <input {...control} type="time" defaultValue="17:30" />}</FormField>
          </FormRow>
        </FormSection>
        <FormSection title="Single column" divider>
          <FormField label="Category">
            {(control) => (
              <select {...control} defaultValue="long">
                <option value="long">An option whose label is much wider than any phone column</option>
              </select>
            )}
          </FormField>
          <FormField label="Notes">{(control) => <textarea {...control} defaultValue="Notes" />}</FormField>
        </FormSection>
      </FormLayout>
    </FormSheet>
  );
}

function LegacySheetFixture() {
  return (
    <BottomSheet title="A sheet without a footer" onDismiss={noop}>
      <p>Sheets that predate FormSheet keep the header close button only.</p>
      <label>Name<input type="text" defaultValue="Emma" /></label>
      <button type="button">Save</button>
    </BottomSheet>
  );
}

const fixtures: Record<string, () => React.ReactNode> = {
  "copy-event": () => <CopyEventSheet event={timedEvent} timeZone="Europe/London" busy={false} error="" onCopy={noop} onCancel={noop} />,
  "copy-event-all-day": () => <CopyEventSheet event={{ ...timedEvent, is_all_day: true, start_at: "2030-11-04T00:00:00Z", end_at: "2030-11-05T00:00:00Z" } as EventOccurrence} timeZone="Europe/London" busy={false} error="" onCopy={noop} onCancel={noop} />,
  "copy-event-error": () => <CopyEventSheet event={timedEvent} timeZone="Europe/London" busy={false} error="We couldn't copy this event to one of the dates. Check your connection and try again." onCopy={noop} onCancel={noop} />,
  primitives: () => <PrimitivesFixture />,
  "legacy-sheet": () => <LegacySheetFixture />,
};

declare global {
  interface Window {
    simulateKeyboard: (keyboardHeight: number) => void;
  }
}

// Drives the real BottomSheet visual-viewport handler with the viewport
// geometry an on-screen keyboard of the given height produces.
window.simulateKeyboard = (keyboardHeight) => {
  const backdrop = document.querySelector<HTMLElement>(".sheet-backdrop");
  if (!backdrop) return;
  const viewport = { scale: 1, height: window.innerHeight - keyboardHeight, offsetTop: 0 } as VisualViewport;
  syncSheetToVisualViewport(backdrop, viewport);
};

const render = fixtures[location.hash.slice(1)];
const container = document.getElementById("root")!;
createRoot(container).render(render ? render() : <p>Unknown fixture</p>);
