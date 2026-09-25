import { useRef } from "react";
import type { ReactNode } from "react";
import { motion, useInView } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";

type LandingProps = { onStart: () => void; googleSignIn?: ReactNode };

const heroVideo ="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_170732_8a9ccda6-5cff-4628-b164-059c500a2b41.mp4";
const featureVideo = heroVideo;

const featureCards = [
  {
    number: "01",
    title: "Structured Lessons",
    items: [
      "Understand the topic step by step",
      "Turn notes into clear explanations",
      "Focus on the concepts that matter",
      "Learn without information overload",
    ],
  },
  {
    number: "02",
    title: "Flashcards & Quizzes",
    items: [
      "Turn concepts into flashcards",
      "Test your understanding",
      "Get instant quiz results",
      "Find what you need to revise",
    ],
  },
  {
    number: "03",
    title: "Progress That Matters",
    items: [
      "Track every learning session",
      "See your scores over time",
      "Follow progress across topics",
      "Return to previous sessions",
    ],
  },
];

const providers = [
  ["01", "GROQ", "Fast AI-powered lesson generation"],
  ["02", "GEMINI", "Flexible AI learning assistance"],
  ["03", "OPENROUTER", "Access multiple AI models"],
];

const flow = [
  ["01", "INPUT", "Give it a topic, notes, or lecture summary."],
  ["02", "LEARN", "Get a structured explanation built around the topic."],
  ["03", "PRACTICE", "Review flashcards and take the quiz."],
  ["04", "REFLECT", "See your score, progress, and areas to revisit."],
];

const ease = [0.16, 1, 0.3, 1] as const;

function Reveal({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const visible = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ y: 24, opacity: 0 }}
      animate={visible ? { y: 0, opacity: 1 } : {}}
      transition={{ duration: 0.8, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <p className="mb-6 text-[10px] uppercase tracking-[.2em] text-primary sm:text-xs">
      {children}
    </p>
  );
}

export default function Landing({ onStart, googleSignIn }: LandingProps) {
  const handleStart = () => {
    onStart();
    window.requestAnimationFrame(() =>
      document
        .getElementById("google-signin")
        ?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
  };

  return (
    <div className="prisma-landing overflow-hidden bg-black text-[#E1E0CC]">
      <section id="top" className="relative h-screen min-h-[680px] p-4 md:p-6">
        <div className="relative h-full overflow-hidden rounded-2xl md:rounded-[2rem]">
          <video
            className="absolute inset-0 h-full w-full object-cover"
            src={heroVideo}
            autoPlay
            loop
            muted
            playsInline
            aria-hidden="true"
          />
          <div className="noise-overlay absolute inset-0 z-[1] opacity-[.7] mix-blend-overlay" />
          <div className="absolute inset-0 z-[2] bg-gradient-to-b from-black/35 via-black/5 to-black/75" />
          <a className="landing-logo" href="#top" aria-label="Curiosity home">
            <img src="/curiosity2.jpg" alt="Curiosity" />
            curiosity
          </a>
          <nav
            className="hero-nav absolute left-1/2 top-0 z-10 flex -translate-x-1/2 gap-3 rounded-b-2xl bg-black px-4 py-2 sm:gap-5 sm:px-6 md:gap-9 md:rounded-b-3xl md:px-8 lg:gap-12"
            aria-label="Primary navigation"
          >
            {["Learn", "History", "Progress", "About"].map((item) => (
              <a
                key={item}
                className="whitespace-nowrap text-[10px] text-[rgba(225,224,204,.8)] transition-colors hover:text-[#E1E0CC] sm:text-xs md:text-sm"
                href={
                  item === "Learn"
                    ? "#top"
                    : item === "History"
                      ? "#history"
                      : item === "Progress"
                        ? "#progress"
                        : "#about"
                }
              >
                {item}
              </a>
            ))}
          </nav>

          <button
            className="hero-login absolute right-6 top-5 z-10 rounded-full border border-primary/40 bg-black/50 px-4 py-2 text-xs text-primary backdrop-blur-md transition-colors hover:bg-primary hover:text-black md:right-10 md:top-8"
            onClick={handleStart}
          >
            Login
          </button>
          <div className="hero-content">
            <div className="hero-copy">
              <Reveal>
                <SectionLabel>A calmer way to learn</SectionLabel>
                <h1 className="hero-heading">
                  Feed your curiosity.
                  <br />
                  Build your
                  <em className="font-serif not-italic text-primary px-4">
                     understanding.
                  <br />
                  </em>
                </h1>
              </Reveal>
            </div>
            <div className="hero-aside">
              <Reveal delay={0.2}>
                <p className="mb-5 text-xs leading-[1.35] text-primary/75 sm:text-sm md:text-base">
                   Give us a topic. Get a complete learning experience
                </p>
                <button
                  className="group flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-medium text-black transition-all hover:gap-3 sm:text-base"
                  onClick={handleStart}
                >
                  Start learning{" "}
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black transition-transform group-hover:scale-110">
                    <ArrowRight size={17} className="text-primary" />
                  </span>
                </button>
                {googleSignIn ? (
                  <div className="mt-4 rounded-xl border border-primary/20 bg-black/65 p-3">
                    <p className="mb-2 text-xs text-primary/70">
                      Sign in with Google to continue your learning journey
                    </p>
                    {googleSignIn}
                  </div>
                ) : (
                  <p className="mt-4 text-xs text-primary/60">
                    Sign in with Google to continue your learning journey
                  </p>
                )}
              </Reveal>
            </div>
          </div>
        </div>
      </section>

      <section id="about" className="bg-black px-4 py-24 sm:px-6 md:py-36">
        <Reveal className="mx-auto max-w-5xl">
          <SectionLabel>The idea</SectionLabel>
          <h2 className="max-w-4xl text-4xl leading-[.95] tracking-[-.04em] sm:text-5xl md:text-6xl lg:text-7xl">
            Learning should feel less like collecting information, and more like{" "}
            <em className="font-serif not-italic text-primary">
              understanding it.
            </em>
          </h2>
          <p className="mt-10 max-w-2xl text-sm leading-relaxed text-gray-400 md:ml-auto md:text-base">
            AI Learning Assistant turns your topics, notes, and lecture
            summaries into structured learning experiences. Learn the concept,
            test what you remember, see how you performed, and come back when
            you&apos;re ready to continue.
          </p>
        </Reveal>
      </section>

      <section
        id="features"
        className="relative bg-[#101010] px-4 py-24 sm:px-6 md:py-32"
      >
        <div className="bg-noise pointer-events-none absolute inset-0 opacity-[.12]" />
        <div className="relative mx-auto max-w-6xl">
          <Reveal>
            <SectionLabel>Built around understanding</SectionLabel>
            <h2 className="max-w-3xl text-4xl leading-[.95] tracking-[-.04em] sm:text-5xl md:text-6xl">
              Everything you need to{" "}
              <em className="font-serif not-italic text-primary">
                actually learn.
              </em>
            </h2>
            <p className="mt-6 max-w-xl text-sm leading-relaxed text-gray-400 md:text-base">
              From your first explanation to your next revision, each session is
              built around understanding and recall.
            </p>
          </Reveal>
          <div className="mt-14 grid gap-3 md:grid-cols-3">
            <motion.article
              className="relative min-h-[390px] overflow-hidden rounded-2xl bg-[#212121] md:min-h-[500px]"
              initial={{ opacity: 0, scale: 0.96 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.8, ease }}
            >
              <video
                className="absolute inset-0 h-full w-full object-cover"
                src={featureVideo}
                autoPlay
                loop
                muted
                playsInline
                aria-hidden="true"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/15 to-transparent" />
              <div className="absolute bottom-6 left-6 right-6">
                <span className="text-xs text-primary/70">
                  THE LEARNING LOOP
                </span>
                <h3 className="mt-3 text-2xl">
                  Explanation → practice → progress
                </h3>
              </div>
            </motion.article>
            {featureCards.map((card, index) => (
              <motion.article
                key={card.title}
                className="flex min-h-[390px] flex-col rounded-2xl border border-white/10 bg-[#212121] p-6 md:min-h-[500px]"
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.8, delay: (index + 1) * 0.12, ease }}
              >
                <span className="text-xs text-primary/60">{card.number}</span>
                <h3 className="mt-16 max-w-[10ch] text-2xl leading-none">
                  {card.title}
                </h3>
                <ul className="mt-8 space-y-3 text-sm leading-snug text-gray-400">
                  {card.items.map((item) => (
                    <li key={item} className="flex gap-2">
                      <Check
                        size={15}
                        className="mt-0.5 shrink-0 text-primary"
                      />
                      {item}
                    </li>
                  ))}
                </ul>

              </motion.article>
            ))}
          </div>
        </div>
      </section>

     
      <section className="bg-[#101010] px-4 py-24 sm:px-6 md:py-32">
        <div className="mx-auto max-w-6xl">
          <Reveal>
            <h2 className="text-4xl tracking-[-.04em] sm:text-5xl md:text-6xl">
              From topic to{" "}
              <em className="font-serif not-italic text-primary">
                understanding.
              </em>
            </h2>
          </Reveal>
          <div className="mt-16 grid gap-0 border-t border-white/15 md:grid-cols-4">
            {flow.map(([number, name, description], index) => (
              <Reveal
                key={name}
                delay={index * 0.1}
                className="border-b border-white/15 py-6 md:border-b-0 md:border-r md:px-5 md:first:pl-0 md:last:border-r-0"
              >
                <span className="text-xs text-primary/50">{number}</span>
                <h3 className="mt-10 text-sm tracking-[.12em]">{name}</h3>
                <p className="mt-4 max-w-[18ch] text-sm leading-relaxed text-gray-400">
                  {description}
                </p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section id="history" className="bg-black px-4 py-24 sm:px-6 md:py-36">
        <div className="mx-auto grid max-w-6xl gap-14 md:grid-cols-2">
          <Reveal>
            <SectionLabel>Your progress</SectionLabel>
            <h2 className="max-w-xl text-4xl leading-[.95] tracking-[-.04em] sm:text-5xl md:text-6xl">
              Learning is a process, not a single session.
            </h2>
            <p className="mt-8 max-w-lg text-sm leading-relaxed text-gray-400 md:text-base">
              Every completed session contributes to your topic progress. Your
              history stays with you, so you can return to what you&apos;ve
              already learned and keep building from there.
            </p>
          </Reveal>
          <Reveal delay={0.15} className="border-t border-white/15 pt-6">
            <h2 className="max-w-md text-3xl leading-tight">
              Never lose where you left off.
            </h2>
            <p className="mt-5 max-w-md text-sm leading-relaxed text-gray-400">
              Your completed learning sessions are saved automatically. Return
              to previous topics, review your results, and continue learning
              without starting over.
            </p>
            <button
              className="mt-8 flex items-center gap-2 rounded-full border border-primary/40 px-5 py-3 text-sm text-primary transition-colors hover:bg-primary hover:text-black"
              onClick={handleStart}
            >
              View learning history <ArrowRight size={16} />
            </button>
          </Reveal>
        </div>
      </section>

      <section
        id="final-cta"
        className="final-learning-cta bg-primary px-4 py-24 text-black sm:px-6 md:py-32"
      >
        <div className="mx-auto max-w-5xl">
          <SectionLabel>Keep learning</SectionLabel>
          <h2 className="max-w-4xl text-5xl leading-[.88] tracking-[-.06em] sm:text-6xl md:text-8xl">
            What do you want to understand?
          </h2>
          <p className="mt-8 text-sm text-black/65 md:text-base">
            Start with a topic. We&apos;ll take it from there.
          </p>
          <button
            className="mt-8 flex items-center gap-2 rounded-full bg-black px-5 py-3 text-sm text-primary transition-transform hover:translate-x-1"
            onClick={handleStart}
          >
            Start learning <ArrowRight size={16} />
          </button>
        </div>
      </section>

      <footer className="landing-page-footer">
        <div className="landing-page-footer-inner">
          <div className="landing-page-footer-brand">
            <strong>curiosity</strong>
            <span>A calmer way to understand.</span>
          </div>
          <a href="mailto:gauravkumar0123zyx@gmail.com">
            Have a question? Get in touch
          </a>
          <span>Learn · Practice · Improve</span>
          <span>© 2026 curiosity</span>
        </div>
      </footer>
    </div>
  );
}
