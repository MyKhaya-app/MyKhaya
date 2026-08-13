export function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .replaceAll(".", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function readableDate(value: string | null | undefined) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function relativeTime(value: string | null | undefined) {
  if (!value) return "Unavailable";
  const elapsed = new Date(value).getTime() - Date.now();
  if (Number.isNaN(elapsed)) return "Unavailable";
  const formatter = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  for (const [unit, milliseconds] of units) {
    if (Math.abs(elapsed) >= milliseconds)
      return formatter.format(Math.round(elapsed / milliseconds), unit);
  }
  return "just now";
}
