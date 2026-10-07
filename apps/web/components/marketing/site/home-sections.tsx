import Link from "next/link";
import { signupPromiseApplies, type SignupStateValue } from "@/components/public-signup";
import { ArrowIcon, CardIcon, HomeIcon, LockIcon } from "./icons";
import { SignupLink, signupIsSignIn } from "./signup-link";

// The example day, how it works, our promise, who it's for, FAQ and final CTA
// sections of the homepage — static copy from the approved design.

const DAY: { time: string; node: "" | "c" | "m"; title: string; text: string; via: string }[] = [
  { time: "07:00", node: "m", title: "The morning summary", text: "A notification lists today's open routines, to-dos and reminders before anyone's out of bed.", via: "Notifications" },
  { time: "07:30", node: "", title: "Feed the dog", text: "A daily household routine. Whoever does it ticks it off, and everyone sees it's done.", via: "Nudges" },
  { time: "09:00", node: "c", title: "Order school lunches", text: "The reminder fires on time. Missed it? Home flags it as overdue so it doesn't slip a second day.", via: "Nudges" },
  { time: "15:00", node: "", title: "School pickup", text: "On the shared calendar with Jamie, Sam and you attached, so nobody assumes someone else is going.", via: "Calendar" },
  { time: "17:00", node: "c", title: "Swimming lesson", text: "Already on Today's card on the Home screen, with the faces of who's going.", via: "Home" },
  { time: "18:00", node: "m", title: "Homemade pizza, 3 eating", text: "Planned at the weekend. The cook is set and everyone knows what's for dinner.", via: "Meal plans" },
];

export function HomeDay() {
  return (
    <section id="day">
      <div className="wrap day">
        <div className="section-head">
          <span className="eyebrow">A day with MyKhaya</span>
          <h2>From breakfast to bedtime.</h2>
          <p className="lede">Here&apos;s how an ordinary Monday might look when the whole household shares one home base.</p>
          <p className="note">An illustrative example day.</p>
        </div>
        <ol className="timeline">
          {DAY.map((item) => (
            <li key={item.time}>
              <time>{item.time}</time>
              <span className={`node${item.node ? ` ${item.node}` : ""}`} />
              <div className="card">
                <h3>{item.title}</h3>
                <p>{item.text}</p>
                <span className="via">{item.via}</span>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function HomeSteps() {
  return (
    <section className="steps-sec" id="how">
      <div className="wrap">
        <div className="section-head center">
          <span className="eyebrow">How it works</span>
          <h2>Up and running in minutes.</h2>
        </div>
        <div className="steps">
          <div className="step"><span className="num">1</span><h3>Create your home</h3><p>Sign up free with no card. Name your home and your calendar, events and notes are ready.</p></div>
          <div className="step"><span className="num">2</span><h3>Invite your people</h3><p>On Family, add adults and children, then invite grandparents and friends from outside the household.</p></div>
          <div className="step"><span className="num">3</span><h3>Share the load</h3><p>Add events, plan meals, set nudges and build lists. Everyone stays in step.</p></div>
        </div>
      </div>
    </section>
  );
}

export function HomePromise() {
  return (
    <section>
      <div className="wrap">
        <div className="section-head">
          <span className="eyebrow">Our promise</span>
          <h2>Built for families. Built to be trusted.</h2>
        </div>
        <div className="trust">
          <div><CardIcon /><h3>No hidden fees</h3><p>Simple, transparent pricing. What you see is what you pay.</p></div>
          <div><ArrowIcon /><h3>Cancel anytime</h3><p>You&apos;re always in control. Change or cancel your plan whenever you like.</p></div>
          <div><HomeIcon /><h3>Built for families</h3><p>Share, organise and do more together, with tools shaped around real households.</p></div>
          <div>
            <LockIcon />
            <h3>Your data, your home</h3>
            <p>
              Private, secure and in your control. Read our <Link href="/legal/privacy">privacy policy</Link> and{" "}
              <Link href="/legal/children">children&apos;s privacy</Link> notice.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export function HomeWho() {
  return (
    <section className="who-sec">
      <div className="wrap">
        <div className="section-head">
          <span className="eyebrow">Who it&apos;s for</span>
          <h2>Every kind of home.</h2>
          <p className="lede">However your household is shaped, MyKhaya gives it one place to come together.</p>
        </div>
        <div className="who">
          <article>
            <div className="avs">
              <span style={{ background: "var(--av-j)" }}>J</span>
              <span style={{ background: "var(--av-s)" }}>S</span>
              <span style={{ background: "var(--av-t)" }}>T</span>
            </div>
            <h3>Busy parents</h3>
            <p>Two diaries, school runs and endless clubs. See it all on one shared calendar.</p>
            <ul><li>Shared family events</li><li>Kids&apos; routines</li><li>Meal plans for the week</li></ul>
          </article>
          <article>
            <div className="avs">
              <span style={{ background: "var(--sage)" }}>G</span>
              <span style={{ background: "var(--mustard)", color: "#2E2006" }}>A</span>
            </div>
            <h3>Extended family</h3>
            <p>Keep grandparents, aunts and close friends in the loop without adding them to every group chat.</p>
            <ul><li>Invite family and friends</li><li>Gift wishlists</li><li>Reminders to call home</li></ul>
          </article>
          <article>
            <div className="avs">
              <span style={{ background: "var(--av-t)" }}>M</span>
            </div>
            <h3>Getting yourself organised</h3>
            <p>Start on your own with the free plan, then bring the household in when you&apos;re ready.</p>
            <ul><li>Calendar, events and notes</li><li>Up to 3 personal routines</li><li>Free forever</li></ul>
          </article>
        </div>
      </div>
    </section>
  );
}

const FAQ: { q: string; a: string }[] = [
  { q: "Is MyKhaya really free?", a: "Yes. The Free plan costs £0 forever and needs no card. It includes the calendar, events, notes, one calendar tag and up to three personal routines for one person." },
  { q: "What's the difference between Free and Family?", a: "Free is for one person getting organised. Family opens MyKhaya up to your whole household, with shared events, lists, gift wishlists, household routines, unlimited tags and routines, and invites for family and friends." },
  { q: "What's the difference between a routine, a reminder and a to-do?", a: "Routines repeat, like feeding the dog every day. Reminders are one-offs at a set time, like calling the grandparents at 9am. To-dos are jobs to tick off when they're done. Each can be personal or shared with the household." },
  { q: "Can children use MyKhaya?", a: "Yes. Children can be members of your household with their own role, so they can see their events and routines. Our children's privacy notice explains how their data is handled." },
  { q: "Can people outside my household join?", a: "Yes. On the Family plan you can invite external family and friends, which is ideal for grandparents, co-parents or the friend who does the Thursday pickup." },
  { q: "Can I cancel at any time?", a: "Yes. There are no hidden fees, and you can change or cancel your plan whenever you like." },
];

/** The last FAQ answer depends on whether Ultimate sign-ups are open (the
 *  same `ultimate_acquisition_enabled` setting that drives the Ultimate card),
 *  so it is only shown while they are actually paused. */
export function HomeFaq({ ultimatePaused }: { ultimatePaused: boolean }) {
  return (
    <section id="faq" style={{ paddingTop: 0 }}>
      <div className="wrap faq-grid">
        <div className="section-head">
          <span className="eyebrow">Questions</span>
          <h2>Good to know.</h2>
          <p className="lede">The things families usually ask before they move in.</p>
          <div className="help-card">
            <b>Still wondering?</b>
            <span>Our support team is happy to help.</span>
            <Link href="/support">Visit Help &amp; Support →</Link>
          </div>
        </div>
        <div className="faq">
          {FAQ.map((item, index) => (
            <details key={item.q} open={index === 0}>
              <summary>{item.q}</summary>
              <p>{item.a}</p>
            </details>
          ))}
          {ultimatePaused && (
            <details>
              <summary>Why can&apos;t I sign up for Ultimate?</summary>
              <p>New Ultimate sign-ups are temporarily paused. You can start on Free or Family today and upgrade when Ultimate reopens.</p>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}

export function HomeCta({ signupState }: { signupState: SignupStateValue }) {
  const promise = signupPromiseApplies(signupState);
  return (
    <section className="cta">
      <div className="wrap">
        <div className="cta-box">
          <div className="blocks" aria-hidden="true">
            <i style={{ background: "var(--coral)" }} />
            <i style={{ background: "var(--on-forest)" }} />
            <i style={{ background: "var(--sage)" }} />
            <i style={{ background: "var(--mustard)" }} />
          </div>
          <div>
            <h2>Ready to bring your family together?</h2>
            {promise === false ? (
              <p>New sign-ups are currently closed.</p>
            ) : (
              <p style={promise === null ? { visibility: "hidden" } : undefined}>Free to start. No card required. Set up in minutes.</p>
            )}
          </div>
          <div className="cta-actions">
            <SignupLink className="btn btn-primary" state={signupState} suffix=" →" />
            {!signupIsSignIn(signupState) && (
              <Link className="btn btn-light" href="/login">
                Sign in
              </Link>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
