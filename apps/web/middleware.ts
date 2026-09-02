import { NextRequest, NextResponse } from "next/server";
import { isPlatformControlCentreHost } from "./components/application-host";
export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  const adminHost = isPlatformControlCentreHost(host);
  const normalizedHost = host.trim().toLowerCase().split(":", 1)[0] ?? "";
  const statusHost =
    normalizedHost === "status.mykhaya.app" ||
    normalizedHost === "status.dev.mykhaya.app" ||
    normalizedHost === "status.localhost";
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
    "img-src 'self' data:",
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
  if (adminHost) {
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
