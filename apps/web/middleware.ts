import { NextRequest, NextResponse } from "next/server";
import { applicationHostKind } from "./components/application-host";
const ADMIN_SESSION_COOKIE = "mk_admin_session";
const ADMIN_PUBLIC_PATHS = ["/login", "/accept-invitation"];

function shouldRedirectToAdminLogin(request: NextRequest): boolean {
  const path = request.nextUrl.pathname;
  if (path.startsWith("/api/")) return false;
  if (ADMIN_PUBLIC_PATHS.some((prefix) => path === prefix || path.startsWith(`${prefix}/`))) return false;
  if (request.method !== "GET" && request.method !== "HEAD") return false;
  if (request.cookies.has(ADMIN_SESSION_COOKIE)) return false;
  // The session cookie is SameSite=Strict, so it is legitimately absent on a
  // cross-site navigation (a link from email/chat) even for a signed-in
  // administrator. Only treat absence as authoritative when the browser would
  // have sent the cookie; otherwise leave it to the client-side gate.
  const site = request.headers.get("sec-fetch-site");
  return site === "none" || site === "same-origin" || site === "same-site";
}

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  const hostKind = applicationHostKind(host);
  const adminHost = hostKind === "admin";
  const statusHost = hostKind === "status";
  if (hostKind === "unknown") return new NextResponse("Misdirected Request", { status: 421 });
  if (adminHost && ["/manifest.webmanifest", "/sw.js"].includes(request.nextUrl.pathname)) {
    return new NextResponse("Not found", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  const internalAdminPath =
    request.nextUrl.pathname.startsWith("/control-centre");
  const internalStatusPath =
    request.nextUrl.pathname.startsWith("/service-status");
  const nonce = btoa(crypto.randomUUID());
  const production = process.env.NODE_ENV === "production";
  const tls =
    request.headers.get("x-forwarded-proto") === "https" ||
    request.nextUrl.protocol === "https:";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${production ? "" : " 'unsafe-eval'"}`,
    adminHost ? "style-src 'self'" : "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    production && tls ? "upgrade-insecure-requests" : "",
  ]
    .filter(Boolean)
    .join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  let response: NextResponse;
  if (adminHost && shouldRedirectToAdminLogin(request)) {
    // Earliest possible point: a browser with no PCC session cookie is sent to
    // the login page before any PCC route renders or any JS runs, so there is
    // nothing to paint. Presence-only UX optimisation — never an authorisation
    // decision; every /platform API still validates the session server-side.
    const proto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() || request.nextUrl.protocol.replace(":", "");
    response = NextResponse.redirect(`${proto}://${host}/login`, 307);
  } else if (adminHost) {
    const url = request.nextUrl.clone();
    url.pathname = `/control-centre${url.pathname === "/" ? "" : url.pathname}`;
    response = NextResponse.rewrite(url, { request: { headers } });
  } else if (statusHost) {
    const url = request.nextUrl.clone();
    url.pathname = "/service-status";
    response = NextResponse.rewrite(url, { request: { headers } });
  } else if (internalAdminPath || internalStatusPath) {
    return new NextResponse("Not found", { status: 404 });
  } else {
    response = NextResponse.next({ request: { headers } });
  }
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );
  if (adminHost) response.headers.set("Cache-Control", "no-store");
  if (statusHost) response.headers.set("Cache-Control", "public, max-age=30");
  return response;
}
export const config = {
  matcher: [
    {
      source:
        "/((?!_next/static|_next/image|favicon.ico|mykhaya-email-logo.png).*)",
    },
  ],
};
