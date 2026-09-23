import Link from "next/link";
import { ChevronLeft } from "lucide-react";

export function SupportBackLink({
  href = "/help-support",
  label = "Help & Support",
}: {
  href?: string;
  label?: string;
}) {
  return (
    <Link className="support-back-link" href={href}>
      <ChevronLeft size={20} aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}
