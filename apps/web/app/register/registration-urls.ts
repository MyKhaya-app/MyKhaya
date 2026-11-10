export function socialRegistrationStartUrl(provider: "apple" | "google", context: string) {
  return `/api/v1/auth/${provider}/start?next_path=${encodeURIComponent(context)}`;
}
