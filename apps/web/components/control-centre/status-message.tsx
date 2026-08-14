import type { ReactNode } from "react";

export function CcNotice({
  tone,
  children,
}: {
  tone: "error" | "success" | "warning";
  children: ReactNode;
}) {
  const isAlert = tone === "error";
  return (
    <p className={`notice ${tone} cc-notice`} role={isAlert ? "alert" : "status"}>
      {children}
    </p>
  );
}
