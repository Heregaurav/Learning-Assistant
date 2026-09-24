import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

type LandingProps = { onStart: () => void; googleSignIn?: ReactNode }

const features = ['Personalized lessons', 'Flashcards that stick', 'Progress you can see']

export default function Landing({ onStart, googleSignIn }: LandingProps) {
  const [scrolled, setScrolled] = useState(false)
  const sectionRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 24)
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const scrollToExperience = () => sectionRef.current?.scrollIntoView({ behavior: 'smooth' })

  return <div className="landing-page">
    <header className={`landing-nav${scrolled ? ' is-scrolled' : ''}`}>
      <a className="landing-brand" href="#top" aria-label="Learning Assistant home">
        <span className="brand-mark">LA</span><span>Learning Assistant</span>
      </a>
      <button className="landing-nav-link" onClick={onStart}>Sign in</button>
    </header>

    <main id="top">
      <section className="landing-hero" ref={sectionRef}>
        <div className="landing-orbit orbit-one" />
        <div className="landing-orbit orbit-two" />
        <p className="landing-kicker">A calmer way to learn</p>
        <h1>Turn curiosity<br /><em>into progress.</em></h1>
        <p className="landing-intro">Bring your notes, questions, and big ideas. Get a focused lesson, useful practice, and a record of what you know.</p>
        {googleSignIn ? <div className="landing-auth-step"><p className="landing-auth-label">Continue with Google to enter your learning space</p>{googleSignIn}<button className="landing-secondary" onClick={() => window.location.reload()}>← Return to landing</button></div> : <div className="landing-actions">
          <button className="landing-primary" onClick={onStart}>Start learning <span aria-hidden="true">↗</span></button>
          <button className="landing-secondary" onClick={scrollToExperience}>Explore the rhythm <span aria-hidden="true">↓</span></button>
        </div>}
        <div className="landing-note"><span className="note-dot" /> Built for steady, private progress</div>
      </section>

      <section className="landing-proof" aria-label="Learning assistant features">
        <div className="proof-heading"><span>01</span><p>Make the next<br /><strong>idea click.</strong></p></div>
        <div className="proof-grid">
          {features.map((feature, index) => <article className="proof-card" key={feature}>
            <span className="proof-number">0{index + 1}</span>
            <h2>{feature}</h2>
            <p>{index === 0 ? 'Meet every topic at the right depth, from first principles to the details that matter.' : index === 1 ? 'Practice the concepts you just met with quick recall and clear explanations.' : 'See your sessions, scores, and topics gather into a picture of your learning.'}</p>
            <span className="proof-arrow" aria-hidden="true">↗</span>
          </article>)}
        </div>
      </section>

      <section className="landing-statement">
        <p className="landing-kicker">Your own learning space</p>
        <h2>Learn deeply.<br /><span>Remember longer.</span></h2>
        <button className="landing-primary" onClick={onStart}>Create your space <span aria-hidden="true">↗</span></button>
      </section>
    </main>

    <footer className="landing-footer">
      <div className="footer-marquee" aria-hidden="true"><span>LEARN WITH INTENTION　✦　TRACK YOUR MOMENTUM　✦　MAKE IT STICK　✦　</span><span>LEARN WITH INTENTION　✦　TRACK YOUR MOMENTUM　✦　MAKE IT STICK　✦　</span></div>
      <div className="footer-bottom"><span>Learning Assistant © 2026</span><span>Made for curious minds</span><button onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>Back to top ↑</button></div>
      <div className="footer-word" aria-hidden="true">LEARN</div>
    </footer>
  </div>
}
