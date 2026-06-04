import Link from "next/link";

import { Reveal } from "./reveal";

/* --- brand primitives --------------------------------------------------- */

function GoldCTA({ children, href = "/app" }: { children: React.ReactNode; href?: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center justify-center rounded-lg bg-primary px-7 py-3.5 font-mono text-xs uppercase tracking-[0.18em] text-primary-foreground shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:opacity-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      {children}
    </Link>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="gold-rule" aria-hidden="true" />
      <p className="eyebrow">{children}</p>
    </div>
  );
}

function SectionHead({ eyebrow, title }: { eyebrow: string; title?: React.ReactNode }) {
  return (
    <div className="mb-10 md:mb-14">
      <Eyebrow>{eyebrow}</Eyebrow>
      {title ? (
        <h2 className="mt-6 max-w-2xl font-serif text-3xl font-medium leading-[1.08] tracking-[-0.01em] md:text-5xl">
          {title}
        </h2>
      ) : null}
    </div>
  );
}

function CheckMark() {
  return (
    <svg
      viewBox="0 0 16 16"
      className="mt-1 h-4 w-4 shrink-0 text-gold"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M3 8.5l3 3 7-8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Section({
  children,
  deep = false,
  id,
}: {
  children: React.ReactNode;
  deep?: boolean;
  id?: string;
}) {
  return (
    <section id={id} className={`px-6 md:px-10 ${deep ? "bg-paper-deep" : ""}`}>
      <div className="mx-auto max-w-5xl border-t border-border py-20 md:py-28">{children}</div>
    </section>
  );
}

/* --- content ------------------------------------------------------------ */

const MOMENTS = [
  {
    title: "Author",
    body: "Describe your strategy in plain English. It becomes an editable checklist that is unmistakably yours.",
  },
  { title: "Prove", body: "Backtest it and see whether the edge holds." },
  {
    title: "Deploy",
    body: "An Agent runs your rules and proposes trades. You approve.",
  },
];

const RULES = [
  "Clavis runs only the logic you authored and confirmed.",
  "It never originates a trade you did not encode.",
  "Non-custodial — your funds stay at your own broker.",
  "Stop-loss and take-profit sit on the order, at the broker — never only inside Clavis.",
  "You are the principal. Clavis is the tool.",
];

const PRODUCTS = [
  {
    name: "Rule Builder",
    line: "Author your strategy as a checklist — plain English in, an editable spec out.",
  },
  {
    name: "Backtest Lab",
    line: "Prove it on history before a cent is at risk.",
    note: "Backtests are historical and are not a promise of future results.",
  },
  {
    name: "Co-Pilot",
    line: "Approve or reject each proposed trade. Your Agent watches the market so you don't have to.",
  },
];

const TIERS = [
  { name: "Free", price: "$0", cadence: "paper only", points: ["Rule Builder", "Backtest Lab", "Paper trading"] },
  { name: "Explorer", price: "$29", cadence: "/mo", points: ["Everything in Free", "Live Co-Pilot", "One live Agent"] },
  {
    name: "Navigator",
    price: "$79",
    cadence: "/mo",
    points: ["Several live Agents", "Trade-management tools"],
    featured: true,
  },
  { name: "Titan", price: "$199", cadence: "/mo", points: ["Partial take-profits", "Priority execution"] },
];

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* header */}
      <header className="sticky top-0 z-20 border-b border-border/70 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4 md:px-10">
          <div className="flex items-center gap-2.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-primary" aria-hidden="true" />
            <span className="font-mono text-sm uppercase tracking-[0.3em]">Clavis</span>
          </div>
          <Link
            href="/app"
            className="rounded-md border border-border px-4 py-2 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-foreground/80 transition-colors hover:border-gold hover:text-foreground"
          >
            Get early access
          </Link>
        </div>
      </header>

      {/* 1. HERO */}
      <section className="relative overflow-hidden px-6 md:px-10">
        <div className="hero-glow pointer-events-none absolute inset-x-0 top-0 h-[460px]" aria-hidden="true" />
        <div className="relative mx-auto max-w-5xl pb-24 pt-20 md:pb-36 md:pt-28">
          <Eyebrow>Authored trading · Early access</Eyebrow>
          <h1 className="mt-8 max-w-4xl font-serif text-[clamp(2.6rem,9vw,5.5rem)] font-medium leading-[1.02] tracking-[-0.025em]">
            Turn your best trading self into software.
          </h1>
          <p className="mt-7 max-w-xl font-serif text-xl leading-relaxed text-muted-foreground md:text-2xl">
            Trading becomes authored, not performed.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-4">
            <GoldCTA>Get early access</GoldCTA>
            <a
              href="#how"
              className="font-mono text-xs uppercase tracking-[0.18em] text-foreground/65 transition-colors hover:text-foreground"
            >
              See how it works →
            </a>
          </div>
        </div>
      </section>

      {/* 2. THE PROBLEM */}
      <Section deep>
        <Eyebrow>The problem</Eyebrow>
        <div className="mt-8 max-w-2xl space-y-5 font-serif text-2xl leading-relaxed md:text-[1.7rem]">
          <p>You don&apos;t lack a strategy. You lack consistent execution.</p>
          <p className="text-muted-foreground">
            Emotion breaks the plan. You move a stop &ldquo;just this once,&rdquo; skip the setup that
            scared you, chase the one you missed. Today you perform your edge by hand — and it costs
            you.
          </p>
        </div>
      </Section>

      {/* 3. THESIS */}
      <Section>
        <Eyebrow>The thesis</Eyebrow>
        <p className="mt-8 max-w-3xl font-serif text-[1.7rem] font-medium leading-[1.18] tracking-[-0.01em] md:text-4xl">
          Clavis is an execution layer for your own authored edge — not an idea generator.
        </p>
        <p className="mt-6 max-w-xl font-serif text-lg text-muted-foreground md:text-xl">
          Your logic, encoded once, and run with discipline.
        </p>
      </Section>

      {/* 4. THE THREE MOMENTS */}
      <Section>
        <SectionHead eyebrow="How it feels" title="Author. Prove. Deploy." />
        <div className="grid gap-5 md:grid-cols-3">
          {MOMENTS.map((moment, i) => (
            <Reveal key={moment.title} delay={i * 110}>
              <div className="group h-full rounded-xl border border-border bg-card p-6 shadow-card transition-all duration-300 hover:-translate-y-1 hover:border-gold/60 md:p-7">
                <span className="numeric text-sm text-gold">0{i + 1}</span>
                <h3 className="mt-4 font-serif text-2xl font-medium">{moment.title}</h3>
                <p className="mt-2 leading-relaxed text-muted-foreground">{moment.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 5. YOUR RULES, NOT SOMEONE ELSE'S */}
      <Section deep>
        <SectionHead eyebrow="Whose rules" title="Your rules, not someone else's." />
        <div className="rounded-2xl border border-border bg-card p-7 shadow-card md:p-12">
          <ul className="grid gap-x-10 gap-y-5 md:grid-cols-2">
            {RULES.map((rule) => (
              <li key={rule} className="flex gap-3 font-serif text-lg leading-relaxed">
                <CheckMark />
                <span>{rule}</span>
              </li>
            ))}
          </ul>
          <div className="mt-8 flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-destructive" aria-hidden="true" />
            <p className="font-mono text-xs uppercase tracking-[0.16em] text-foreground/80">
              One kill switch stops every Agent, instantly.
            </p>
          </div>
        </div>
      </Section>

      {/* 6. HOW IT WORKS */}
      <Section id="how">
        <SectionHead eyebrow="How it works" title="Three tools, one loop." />
        <div className="grid gap-5 md:grid-cols-3">
          {PRODUCTS.map((product, i) => (
            <Reveal key={product.name} delay={i * 110}>
              <div className="flex h-full flex-col rounded-xl border border-border bg-card p-6 shadow-card transition-all duration-300 hover:-translate-y-1 hover:border-gold/60 md:p-7">
                <span className="numeric text-xs text-muted-foreground">0{i + 1}</span>
                <h3 className="mt-3 font-serif text-xl font-medium">{product.name}</h3>
                <p className="mt-2 flex-1 leading-relaxed text-muted-foreground">{product.line}</p>
                {product.note ? (
                  <p className="mt-5 border-t border-border pt-3 font-mono text-[0.62rem] uppercase leading-relaxed tracking-[0.1em] text-muted-foreground">
                    {product.note}
                  </p>
                ) : null}
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 7. MISSION */}
      <Section deep>
        <SectionHead eyebrow="The mission" title="Bring authored trading to everyone." />
        <div className="max-w-2xl space-y-5 font-serif text-lg leading-relaxed text-muted-foreground md:text-xl">
          <p>
            I built Clavis after years of hearing the same thing from traders: they had an edge, but
            couldn&apos;t carry the psychological load of executing it by hand. They wished they could
            trade — and couldn&apos;t.
          </p>
          <p>
            So Clavis holds the discipline, and leaves the judgment with you. That is the whole idea,
            and it is the only proof I&apos;ll offer you today — honestly, in my own words, instead of
            logos or numbers I haven&apos;t earned yet.
          </p>
          <p className="font-mono text-xs uppercase tracking-[0.18em] text-foreground/70">— The founder</p>
        </div>
      </Section>

      {/* 8. PRICING */}
      <Section>
        <SectionHead eyebrow="Pricing" title="Paper is free. Live is the unlock." />
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`relative flex h-full flex-col rounded-xl border bg-card p-6 shadow-card ${
                tier.featured ? "border-gold ring-1 ring-gold/25" : "border-border"
              }`}
            >
              {tier.featured ? (
                <span className="absolute -top-3 left-6 rounded-full bg-primary px-3 py-1 font-mono text-[0.58rem] uppercase tracking-[0.16em] text-primary-foreground">
                  Most popular
                </span>
              ) : null}
              <p className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">{tier.name}</p>
              <p className="mt-3 font-serif text-4xl font-medium">
                <span className="numeric">{tier.price}</span>
                <span className="ml-1 font-serif text-base text-muted-foreground">{tier.cadence}</span>
              </p>
              <ul className="mt-6 space-y-2.5 text-sm text-muted-foreground">
                {tier.points.map((point) => (
                  <li key={point} className="flex gap-2.5">
                    <CheckMark />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-8 font-mono text-[0.7rem] uppercase leading-relaxed tracking-[0.12em] text-muted-foreground">
          Annual billing = two months free · Launch offer: the first 50 users keep 30% off for life ·
          Live execution is the paid unlock; paper trading is always free.
        </p>
      </Section>

      {/* 9. CLOSING CTA */}
      <section className="bg-paper-deep px-6 md:px-10">
        <div className="mx-auto max-w-5xl border-t border-border py-24 text-center md:py-32">
          <span className="gold-rule mx-auto" aria-hidden="true" />
          <h2 className="mx-auto mt-8 max-w-2xl font-serif text-4xl font-medium leading-[1.08] tracking-[-0.01em] md:text-6xl">
            Your best self trades for you.
          </h2>
          <div className="mt-10 flex justify-center">
            <GoldCTA>Get early access</GoldCTA>
          </div>
        </div>
      </section>

      {/* 10. FOOTER */}
      <footer className="border-t border-border px-6 py-14 md:px-10">
        <div className="mx-auto max-w-5xl">
          <div className="flex flex-col gap-10 md:flex-row md:justify-between">
            <div className="flex items-center gap-2.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-primary" aria-hidden="true" />
              <span className="font-mono text-sm uppercase tracking-[0.3em]">Clavis</span>
            </div>
            <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
              <FooterGroup title="Product" links={["Rule Builder", "Backtest Lab", "Co-Pilot"]} />
              <FooterGroup title="Company" links={["Mission", "Pricing"]} />
              <FooterGroup title="Legal" links={["Risk disclosure", "Terms", "Privacy"]} />
            </div>
          </div>
          <p className="mt-12 max-w-3xl font-mono text-[0.68rem] leading-relaxed tracking-[0.04em] text-muted-foreground">
            Clavis is software, not financial advice. Trading leveraged instruments carries
            substantial risk, including the loss of more than your deposit. Clavis makes no promise or
            guarantee of returns. Backtested and past performance does not indicate future results.
          </p>
        </div>
      </footer>
    </div>
  );
}

function FooterGroup({ title, links }: { title: string; links: string[] }) {
  return (
    <div>
      <p className="eyebrow mb-3">{title}</p>
      <ul className="space-y-2.5">
        {links.map((link) => (
          <li key={link}>
            <span className="text-sm text-muted-foreground transition-colors hover:text-foreground">{link}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
