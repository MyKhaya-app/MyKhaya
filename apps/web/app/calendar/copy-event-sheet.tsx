"use client";

import { useRef, useState } from "react";
import type { EventOccurrence } from "@mykhaya/shared-types";
import { FormField, FormLayout, FormRow, FormSection, FormSheet } from "@/components/form-layout";
import { displayDate } from "./calendar-utils";
import { eventWhenSummary } from "./event-when-summary";

export type CopyDestination = { date: string; startTime: string; endTime: string };

// Copy Event is the reference implementation of the shared form layout
// (components/form-layout.tsx, docs/design/forms.md): each destination is a
// framed FormSection with its date on its own row and Start/End in a
// two-column FormRow that stacks when the card is too narrow for both.
export function CopyEventSheet({
  event,
  timeZone,
  busy,
  error,
  onCopy,
  onCancel,
}: {
  event: EventOccurrence;
  timeZone: string;
  busy: boolean;
  error: string;
  onCopy: (destinations: CopyDestination[]) => void;
  onCancel: () => void;
}) {
  const eventZone = event.timezone || timeZone;
  const sourceSummary = eventWhenSummary(event, timeZone);
  const sourceStartTime = displayDate(event.start_at, { hour: "2-digit", minute: "2-digit", hour12: false }, eventZone);
  const sourceEndTime = displayDate(event.end_at, { hour: "2-digit", minute: "2-digit", hour12: false }, eventZone);
  type DestinationDraft = { id: number; date: string; startTime: string; endTime: string };
  const nextId = useRef(2);
  const [destinations, setDestinations] = useState<DestinationDraft[]>([
    { id: 1, date: "", startTime: sourceStartTime, endTime: sourceEndTime },
  ]);

  function updateDestination(id: number, field: "date" | "startTime" | "endTime", value: string) {
    setDestinations((current) => current.map((destination) => destination.id === id ? { ...destination, [field]: value } : destination));
  }
  function addDestination() {
    setDestinations((current) => [
      ...current,
      { id: nextId.current++, date: "", startTime: sourceStartTime, endTime: sourceEndTime },
    ]);
  }
  function removeDestination(id: number) {
    setDestinations((current) => current.filter((destination) => destination.id !== id));
  }
  const dates = destinations.map((destination) => destination.date).filter(Boolean);
  const hasDuplicateDates = new Set(dates).size !== dates.length;
  const hasInvalidTimes = !event.is_all_day && destinations.some((destination) =>
    !destination.startTime || !destination.endTime || destination.endTime <= destination.startTime,
  );
  const canSubmit = destinations.length > 0 && destinations.every((destination) => destination.date) && !hasDuplicateDates && !hasInvalidTimes;

  return (
    <FormSheet
      title="Copy event"
      onDismiss={onCancel}
      busy={busy}
      primaryAction={
        <button type="button" onClick={() => canSubmit && onCopy(destinations)} disabled={busy || !canSubmit}>
          {busy ? "Copying…" : `Copy event${destinations.length > 1 ? ` (${destinations.length})` : ""}`}
        </button>
      }
    >
      <FormLayout className="copy-event-form">
        <div className="copy-event-source" aria-label="Original event">
          <span className="eyebrow">Original event</span>
          <strong>{event.title}</strong>
          <span>{sourceSummary.dateLine}</span>
          <span>{sourceSummary.timeLine}</span>
        </div>
        {destinations.map((destination, index) => (
          <FormSection
            key={destination.id}
            framed
            title={`Destination ${index + 1}`}
            actions={index > 0 ? (
              <button className="secondary" type="button" onClick={() => removeDestination(destination.id)}>Remove destination</button>
            ) : null}
          >
            <FormField label="Date">
              {(control) => (
                <input {...control} type="date" placeholder="Choose a date" value={destination.date} onChange={(e) => updateDestination(destination.id, "date", e.target.value)} />
              )}
            </FormField>
            {!event.is_all_day && (
              <FormRow>
                <FormField label="Start time">
                  {(control) => (
                    <input {...control} type="time" value={destination.startTime} onChange={(e) => updateDestination(destination.id, "startTime", e.target.value)} />
                  )}
                </FormField>
                <FormField label="End time">
                  {(control) => (
                    <input {...control} type="time" value={destination.endTime} onChange={(e) => updateDestination(destination.id, "endTime", e.target.value)} />
                  )}
                </FormField>
              </FormRow>
            )}
          </FormSection>
        ))}
        <button className="secondary copy-event-add" type="button" onClick={addDestination}>Add another date</button>
        {hasDuplicateDates && <p className="notice error" role="alert">Choose a different date for each destination.</p>}
        {hasInvalidTimes && <p className="notice error" role="alert">Each destination needs an end time after its start time.</p>}
        {error && <p className="notice error" role="alert">{error}</p>}
      </FormLayout>
    </FormSheet>
  );
}
