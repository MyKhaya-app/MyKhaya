import type { EventOccurrence } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";

// The canonical "everything this Home/user can see" event set for a date
// range: this Home's own calendar plus every externally shared MyKhaya
// calendar accepted into it — the same two sources, fetched the same way
// (a single range-bounded listEvents/listSharedEvents call per source,
// not the "next N occurrences" cursor pagination
// listUpcomingEvents/listUpcomingSharedEvents use for a short preview
// list), that the Calendar page's own load() merges for whatever range is
// currently on screen. Extracted here so any other page that needs an
// honest "how many events are visible in this window" count — not just a
// capped preview — asks the same question Calendar itself would answer,
// rather than inventing a narrower definition. page_size is generous
// (300, matching Calendar's own request) rather than paginated via
// next_page: real household + shared calendar volume for a week/month
// window has never approached that in practice, and Calendar's own load()
// makes the same trade-off.
export async function fetchVisibleEventsInRange(
  homeId: string,
  range: { start_at: string; end_at: string },
): Promise<EventOccurrence[]> {
  const [homeEvents, shares] = await Promise.all([
    api.listEvents(homeId, { start_at: range.start_at, end_at: range.end_at, page_size: 300 }),
    api.sharedCalendars().catch(() => ({ items: [] })),
  ]);
  const sharedEventLists = await Promise.all(
    shares.items.map((share) =>
      api
        .listSharedEvents(share.id, range)
        .then((response) =>
          response.items.map(
            (item): EventOccurrence => ({
              ...item,
              share_id: share.id,
              share_permission: share.permission,
              shared_by_home_name: share.source_group_name,
            }),
          ),
        )
        .catch(() => []),
    ),
  );
  return [...homeEvents.items, ...sharedEventLists.flat()];
}
