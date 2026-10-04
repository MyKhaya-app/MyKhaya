import Link from "next/link";

// The one consistent small treatment used wherever a Free Home encounters a
// Family-only restriction (Invite household members, Household routines,
// event categories, ...). Never mentions a price — Plan & Billing
// (/settings/billing) is the single place pricing is shown, always resolved
// live rather than hard-coded. See docs/product/plans-and-pricing.md.
export function FamilyUpsell({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="card details family-upsell">
      <p>
        <strong>{title}</strong>
      </p>
      {description && <p className="muted">{description}</p>}
      <Link className="button secondary" href="/settings/billing">
        View Family plan
      </Link>
    </div>
  );
}
