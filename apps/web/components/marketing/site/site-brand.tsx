import Link from "next/link";

export const LOGO_SMALL = "/images/marketing/mykhaya-logo-64.png";
export const LOGO_LARGE = "/images/marketing/mykhaya-logo-256.png";

export function SiteBrand({ label }: { label?: string }) {
  return (
    <Link className="brand" href="/" aria-label={label}>
      <img src={LOGO_SMALL} alt="" width={40} height={40} />
      MyKhaya
    </Link>
  );
}
