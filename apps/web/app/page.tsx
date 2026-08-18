import { PublicBenefits } from "@/components/marketing/public-benefits";
import { PublicFeatures } from "@/components/marketing/public-features";
import { PublicFinalCta } from "@/components/marketing/public-final-cta";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";
import { PublicHero } from "@/components/marketing/public-hero";
import { PublicHowItWorks } from "@/components/marketing/public-how-it-works";
import { PublicPricing } from "@/components/marketing/public-pricing";

export default function Welcome() {
  return (
    <main className="mk-page">
      <PublicHeader />
      <PublicHero />
      <PublicBenefits />
      <PublicFeatures />
      <PublicHowItWorks />
      <PublicPricing />
      <PublicFinalCta />
      <PublicFooter />
    </main>
  );
}
