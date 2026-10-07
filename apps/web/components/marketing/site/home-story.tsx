import { ClockIcon, PeopleIcon, WavesIcon } from "./icons";
import { LOGO_LARGE } from "./site-brand";

export function HomeStory() {
  return (
    <section>
      <div className="wrap story">
        <div className="story-visual" aria-hidden="true">
          <img className="logo-tile" src={LOGO_LARGE} alt="" width={240} height={240} loading="lazy" decoding="async" />
          <div className="member m1"><span className="av" style={{ background: "var(--av-j)" }}>J</span><div><b>Jamie</b><small>Adult</small></div></div>
          <div className="member m2"><span className="av" style={{ background: "var(--av-s)" }}>S</span><div><b>Sam</b><small>Child</small></div></div>
          <div className="member m3"><span className="av" style={{ background: "var(--av-t)" }}>T</span><div><b>You</b><small>Home Admin</small></div></div>
        </div>
        <div className="story-copy">
          <span className="eyebrow">Why families choose MyKhaya</span>
          <h2>Less organising. More being together.</h2>
          <p className="lede">
            Every home runs on a mental to-do list, and too often one person carries it. MyKhaya puts it somewhere
            everyone can see, so the load is shared and nothing slips.
          </p>
          <div className="pillars">
            <div className="pillar">
              <span className="ic" style={{ background: "var(--coral-soft)" }}><PeopleIcon size={24} /></span>
              <div><h3>Stronger family connections</h3><p>Everyone sees the same plan, from the school pickup to the family day out.</p></div>
            </div>
            <div className="pillar">
              <span className="ic" style={{ background: "var(--mustard-soft)" }}><WavesIcon size={24} /></span>
              <div><h3>Less stress, more calm</h3><p>Gentle nudges replace the nagging, and overdue jobs are flagged before they become emergencies.</p></div>
            </div>
            <div className="pillar">
              <span className="ic" style={{ background: "var(--tint)" }}><ClockIcon size={24} /></span>
              <div><h3>More time for what matters</h3><p>Fewer group-chat threads and lost notes. More evenings that are actually free.</p></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
