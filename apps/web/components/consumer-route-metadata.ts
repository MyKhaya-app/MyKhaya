export type ConsumerRouteMetadata = {
  backFallback?: string;
};

/**
 * The consumer shell's navigation contract. Root tab destinations deliberately
 * have no fallback; every other eligible screen gets a safe in-app parent for
 * direct links where browser history has no MyKhaya entry.
 */
export function consumerRouteMetadata(pathname: string): ConsumerRouteMetadata {
  if (["/home", "/calendar", "/people", "/settings"].includes(pathname)) return {};

  if (pathname === "/driveway/add" || pathname === "/driveway/lookup") {
    return { backFallback: "/driveway" };
  }
  if (pathname === "/driveway/lookup/report") return { backFallback: "/driveway/lookup" };
  const vehicleMatch = pathname.match(/^\/driveway\/([^/]+)(\/.*)?$/);
  if (vehicleMatch?.[1]) {
    return { backFallback: vehicleMatch[2] ? `/driveway/${vehicleMatch[1]}` : "/driveway" };
  }
  if (pathname.startsWith("/lists/")) return { backFallback: "/lists" };
  if (pathname.startsWith("/wish-lists/")) return { backFallback: "/wish-lists" };
  if (pathname.startsWith("/calendar/")) return { backFallback: "/calendar" };
  if (pathname.startsWith("/calendar-shares/")) return { backFallback: "/calendar" };
  if (pathname.startsWith("/help-support/requests/")) return { backFallback: "/help-support/requests" };
  if (pathname.startsWith("/help-support/")) return { backFallback: "/help-support" };
  if (pathname.startsWith("/about/")) return { backFallback: "/about" };
  if (pathname.startsWith("/budget/")) return { backFallback: "/budget" };
  if (pathname.startsWith("/settings/")) return { backFallback: "/settings" };
  if (pathname.startsWith("/khaya-control-centre/")) return { backFallback: "/settings" };
  if (["/lists", "/meal-plans", "/wish-lists", "/budget", "/driveway", "/help-support", "/about", "/me/notifications", "/settings/routines-reminders"].includes(pathname)) {
    return { backFallback: "/settings" };
  }
  return {};
}
