import Link from "next/link";

export function PublicFinalCta() {
  return (
    <section className="mk-final-cta" aria-labelledby="final-cta-heading">
      <h2 id="final-cta-heading">Ready to bring your family together?</h2>
      <p>Free to start. No card required.</p>
      <Link className="button large mk-final-cta-button" href="/register">
        Get started free
      </Link>
    </section>
  );
}
