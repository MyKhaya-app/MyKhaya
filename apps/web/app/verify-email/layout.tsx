import { RouteSuspense } from "@/components/route-suspense";
export default function Layout({ children }: { children: React.ReactNode }) {
  return <RouteSuspense>{children}</RouteSuspense>;
}
