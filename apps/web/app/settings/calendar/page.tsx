"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { CalendarDays, Check, ChevronDown, Info } from "lucide-react";
import type { HomeCalendar, NotificationPreferences } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";

const REMINDER_OPTIONS = [
  [15, "15 minutes"],
  [30, "30 minutes"],
  [60, "1 hour"],
  [120, "2 hours"],
] as const;

function CalendarSelect({
  value,
  onChange,
  children,
  label,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
  /** The control's accessible name — the visible words beside it are not associated with it. */
  label: string;
  disabled?: boolean;
}) {
  return (
    <span className="calendar-settings-select">
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
      <ChevronDown size={18} aria-hidden="true" />
    </span>
  );
}

function CheckBox({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <label className="calendar-settings-check">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span aria-hidden="true"><Check size={18} strokeWidth={2.5} /></span>
      <span className="sr-only">{label}</span>
    </label>
  );
}

export default function CalendarSettingsPage() {
  const { activeHomeId } = useActiveHome();
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [calendars, setCalendars] = useState<HomeCalendar[]>([]);
  const [personalCalendar, setPersonalCalendar] = useState<HomeCalendar | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const preferences = await api.notificationPreferences();
    setPrefs(preferences);
    if (activeHomeId) {
      const result = await api.listCalendars(activeHomeId);
      setCalendars(result.items);
      setPersonalCalendar(result.personal_calendar);
    }
  }, [activeHomeId]);

  useEffect(() => { load().catch((cause: Error) => setError(cause.message)); }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!prefs) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.updateNotificationPreferences({
        ...prefs,
        default_event_reminder_enabled: prefs.default_event_reminder_enabled,
        default_event_reminder_minutes: prefs.default_event_reminder_minutes,
        all_day_reminder_enabled: prefs.all_day_reminder_enabled,
        all_day_reminder_time: prefs.all_day_reminder_time,
        default_calendar_id: prefs.default_calendar_id,
        week_starts_on: prefs.week_starts_on,
        show_declined_events: prefs.show_declined_events,
      });
      setPrefs(updated);
      setMessage("Calendar settings saved.");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!prefs) {
    return <SettingsPage title="Calendar settings" backLink={{ href: "/settings", label: "Back to More" }}><p role="status">Loading…</p></SettingsPage>;
  }

  const calendarOptions = [...calendars, ...(personalCalendar ? [personalCalendar] : [])];
  const selectedReminder = REMINDER_OPTIONS.some(([minutes]) => minutes === prefs.default_event_reminder_minutes)
    ? String(prefs.default_event_reminder_minutes)
    : "30";

  return (
    <SettingsPage title="Calendar settings" backLink={{ href: "/settings", label: "Back to More" }} className="calendar-settings-page">
      {error && <p className="notice error" role="alert">{error}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      <form onSubmit={save}>
        <section className="calendar-settings-info" aria-label="Personal calendar settings">
          <span className="calendar-settings-info-icon"><Info size={24} aria-hidden="true" /></span>
          <div><strong>Personal calendar settings for you.</strong><p>These settings only apply to you and do not affect other members of your Home.</p></div>
        </section>

        <section className="card calendar-settings-card">
          <h2>Reminders</h2>
          <p className="calendar-settings-card-intro">Choose when MyKhaya reminds you about events you&rsquo;re attending.</p>
          <div className="calendar-settings-row">
            <CheckBox checked={prefs.default_event_reminder_enabled} onChange={(value) => setPrefs({ ...prefs, default_event_reminder_enabled: value })} label="Remind me before events I’m attending" />
            <span>Remind me</span>
            <CalendarSelect label="Reminder time before events" value={selectedReminder} disabled={!prefs.default_event_reminder_enabled} onChange={(value) => setPrefs({ ...prefs, default_event_reminder_minutes: Number(value) })}>
              {REMINDER_OPTIONS.map(([minutes, label]) => <option value={minutes} key={minutes}>{label}</option>)}
            </CalendarSelect>
            <span>before events I&rsquo;m attending</span>
          </div>
          <div className="calendar-settings-row">
            <CheckBox checked={prefs.all_day_reminder_enabled} onChange={(value) => setPrefs({ ...prefs, all_day_reminder_enabled: value })} label="Remind me about all-day events" />
            <span>Remind me about all-day events at</span>
            <CalendarSelect label="All-day reminder time" value={prefs.all_day_reminder_time} onChange={(value) => setPrefs({ ...prefs, all_day_reminder_time: value })}>
              {['08:00', '09:00', '10:00', '12:00'].map((time) => <option value={time} key={time}>{time}</option>)}
            </CalendarSelect>
          </div>
          <p className="muted calendar-settings-supporting-copy">This includes birthdays, school days and other all-day events.</p>
        </section>

        <section className="card calendar-settings-card">
          <h2>Defaults</h2>
          <p className="calendar-settings-card-intro">Set your preferred defaults for new events and how your calendar displays.</p>
          <div className="calendar-settings-row calendar-settings-default-row">
            <span className="calendar-settings-icon lavender"><CalendarDays size={24} aria-hidden="true" /></span>
            <span><strong>Default calendar</strong><small>New events will be added to this calendar by default.</small></span>
            <CalendarSelect label="Default calendar" value={prefs.default_calendar_id ?? ""} onChange={(value) => setPrefs({ ...prefs, default_calendar_id: value || null })}>
              <option value="">Home Calendar</option>
              {calendarOptions.map((calendar) => <option value={calendar.id} key={calendar.id}>{calendar.name}</option>)}
            </CalendarSelect>
          </div>
          <div className="calendar-settings-row calendar-settings-default-row">
            <span className="calendar-settings-icon blue"><CalendarDays size={24} aria-hidden="true" /></span>
            <span><strong>Week starts on</strong><small>Choose which day your calendar weeks start on.</small></span>
            <CalendarSelect label="Week starts on" value={prefs.week_starts_on} onChange={(value) => setPrefs({ ...prefs, week_starts_on: value as "monday" | "sunday" })}>
              <option value="monday">Monday</option><option value="sunday">Sunday</option>
            </CalendarSelect>
          </div>
        </section>

        <section className="card calendar-settings-card">
          <h2>Display</h2>
          <p className="calendar-settings-card-intro">Choose what you see in your calendar.</p>
          <div className="calendar-settings-row calendar-settings-default-row">
            <CheckBox checked={prefs.show_declined_events} onChange={(value) => setPrefs({ ...prefs, show_declined_events: value })} label="Show events I’ve declined" />
            <span><strong>Show events I&rsquo;ve declined</strong><small>Events you&rsquo;ve declined will still appear in your calendar.</small></span>
          </div>
        </section>
        <button className="primary calendar-settings-save" disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
      </form>
    </SettingsPage>
  );
}
