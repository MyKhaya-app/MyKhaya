import { Suspense } from "react";

export function RouteSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<main className="auth-page" aria-busy="true" />}>
      {children}
    </Suspense>
  );
}
