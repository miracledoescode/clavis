import Link from "next/link";

import { Reveal } from "./reveal";

/* --- small brand primitives --------------------------------------------- */

function GoldCTA({ children, href = "/app" }: { children: React.ReactNode; href?: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center justify-center rounded bg-primary px-7 py-3.5 font-mono text-xs uppercase tracking-[0.18em] text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      {children}
    </Link>
  );
}

function Section({
  eyebrow,
  title,
  children,
  deep = false,
}: {
  eyebrow?: string;
  title?: React.ReactNode;
  children?: React.ReactNode;
  deep?: boolean;
}) {
  return (
    <section className={`px-5 md:px-8 ${deep ? "bg-paper-deep" : ""}`}>
      <div className="mx-auto max-w-5xl border-t border-border py-16 md:py-24">
        {eyebrow ? <p className="eyebrow mb-5">{eyebrow}</p> : null}
        {title ? (
          <h2 className="mb-8 max-w-2xl font-serif text-3xl font-medium leading-[1.12] md:text-5xl">
            {title}
          </h2>
        ) : null}
        {children}
      </div>
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
  {
    name: "Free",
    price: "$0",
    cadence: "paper only",
    points: ["Rule Builder", "Backtest Lab", "Paper trading"],
  },
  {
    name: "Explorer",
    price: "$29",
    cadence: "/mo",
    points: ["Everything in Free", "Live Co-Pilot", "One live Agent"],
  },
  {
    name: "Navigator",
    price: "$79",
    cadence: "/mo",
    points: ["Several live Agents", "Trade-management tools"],
    featured: true,
  },
  {
    name: "Titan",
    price: "$199",
    cadence: "/mo",
    points: ["Partial take-profits", "Priority execution"],
  },
];

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* header — restrained */}
      <header className="sticky top-0 z-20 border-b border-border/70 bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4 md:px-8">
          <span className="font-mono text-sm uppercase tracking-[0.3em]">Clavis</span>
          <Link
            href="/app"
            className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-foreground/75 transition-colors hover:text-foreground"
          >
            Get early access
          </Link>
        </div>
      </header>

      {/* 1. HERO — nothing else above the fold */}
      <section className="px-5 md:px-8">
        <div className="mx-auto max-w-5xl pb-20 pt-24 md:pb-32 md:pt-36">
          <h1 className="max-w-3xl font-serif text-[2.7rem] font-medium leading-[1.04] tracking-tight md:text-7xl">
            Turn your best trading self into software.
          </h1>
          <p className="mt-6 max-w-xl font-serif text-lg text-muted-foreground md:text-2xl">
            Trading becomes authored, not performed.
          </p>
          <div className="mt-10">
            <GoldCTA>Get early access</GoldCTA>
          </div>
        </div>
      </section>

      {/* 2. THE PROBLEM — truth, not borrowed logos */}
      <Section eyebrow="The problem" deep>
        <div className="max-w-2xl space-y-5 font-serif text-xl leading-relaxed md:text-2xl">
          <p>You don&apos;t lack a strategy. You lack consistent execution.</p>
          <p className="text-muted-foreground">
            Emotion breaks the plan. You move a stop &ldquo;just this once,&rdquo; skip the setup that
            scared you, chase the one you missed. Today you perform your edge by hand — and it costs
            you.
          </p>
        </div>
      </Section>

      {/* 3. THESIS */}
      <Section eyebrow="The thesis">
        <p className="max-w-3xl font-serif text-2xl font-medium leading-snug md:text-4xl">
          Clavis is an execution layer for your own authored edge — not an idea generator.
        </p>
        <p className="mt-5 max-w-xl font-serif text-lg text-muted-foreground md:text-xl">
          Your logic, encoded once, and run with discipline.
        </p>
      </Section>

      {/* 4. THE THREE MOMENTS */}
      <Section eyebrow="How it feels" title="Author. Prove. Deploy.">
        <div className="grid gap-5 md:grid-cols-3">
          {MOMENTS.map((moment, i) => (
            <Reveal key={moment.title} delay={i * 120}>
              <div className="h-full rounded-lg border border-border bg-card p-6">
                <span className="numeric text-sm text-gold">0{i + 1}</span>
                <h3 className="mt-3 font-serif text-2xl font-medium">{moment.title}</h3>
                <p className="mt-2 text-muted-foreground">{moment.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 5. YOUR RULES, NOT SOMEONE ELSE'S */}
      <Section eyebrow="Whose rules" title="Your rules, not someone else's.">
        <div className="rounded-lg border border-border bg-card p-7 md:p-10">
          <ul className="space-y-4 font-serif text-lg leading-relaxed md:text-xl">
            <li>Clavis runs only the logic you authored and confirmed.</li>
            <li>It never originates a trade you did not encode.</li>
            <li>Non-custodial — your funds stay at your own broker.</li>
            <li>
              Your stop-loss and take-profit are set on the order, at the broker — never held only
              inside Clavis.
            </li>
            <li>You are the principal. Clavis is the tool.</li>
          </ul>
          <div className="mt-7 flex items-start gap-3 border-t border-border pt-6">
            <span
              className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-destructive"
              aria-hidden="true"
            />
            <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted-foreground">
              One kill switch stops every Agent, instantly.
            </p>
          </div>
        </div>
      </Section>

      {/* 6. HOW IT WORKS */}
      <Section eyebrow="How it works" title="Three tools, one loop.">
        <div className="grid gap-5 md:grid-cols-3">
          {PRODUCTS.map((product) => (
            <div key={product.name} className="flex h-full flex-col rounded-lg border border-border bg-card p-6">
              <h3 className="font-serif text-xl font-medium">{product.name}</h3>
              <p className="mt-2 flex-1 text-muted-foreground">{product.line}</p>
              {product.note ? (
                <p className="mt-4 border-t border-border pt-3 font-mono text-[0.65rem] uppercase leading-relaxed tracking-[0.12em] text-muted-foreground">
                  {product.note}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </Section>

      {/* 7. MISSION — the honest social proof */}
      <Section eyebrow="The mission" title="Bring authored trading to everyone." deep>
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
          <p className="font-mono text-xs uppercase tracking-[0.18em] text-foreground/70">
            — The founder
          </p>
        </div>
      </Section>

      {/* 8. PRICING */}
      <Section eyebrow="Pricing" title="Paper is free. Live is the unlock.">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`flex h-full flex-col rounded-lg border bg-card p-6 ${
                tier.featured ? "border-gold" : "border-border"
              }`}
            >
              <p className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">
                {tier.name}
              </p>
              <p className="mt-3 font-serif text-3xl font-medium">
                <span className="numeric">{tier.price}</span>
                <span className="ml-1 text-base text-muted-foreground">{tier.cadence}</span>
              </p>
              <ul className="mt-5 space-y-2 text-sm text-muted-foreground">
                {tier.points.map((point) => (
                  <li key={point} className="flex gap-2">
                    <span className="text-gold" aria-hidden="true">
                      ·
                    </span>
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-6 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-muted-foreground">
          Annual billing = two months free · Launch offer: the first 50 users keep 30% off for life ·
          Live execution is the paid unlock; paper trading is always free.
        </p>
      </Section>

      {/* 9. CLOSING CTA */}
      <section className="bg-paper-deep px-5 md:px-8">
        <div className="mx-auto max-w-5xl border-t border-border py-20 text-center md:py-28">
          <h2 className="mx-auto max-w-2xl font-serif text-4xl font-medium leading-[1.1] md:text-6xl">
            Your best self trades for you.
          </h2>
          <div className="mt-9 flex justify-center">
            <GoldCTA>Get early access</GoldCTA>
          </div>
        </div>
      </section>

      {/* 10. FOOTER */}
      <footer className="border-t border-border px-5 py-12 md:px-8">
        <div className="mx-auto max-w-5xl">
          <div className="flex flex-col gap-8 md:flex-row md:justify-between">
            <span className="font-mono text-sm uppercase tracking-[0.3em]">Clavis</span>
            <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
              <FooterGroup
                title="Product"
                links={["Rule Builder", "Backtest Lab", "Co-Pilot"]}
              />
              <FooterGroup title="Company" links={["Mission", "Pricing"]} />
              <FooterGroup title="Legal" links={["Risk disclosure", "Terms", "Privacy"]} />
            </div>
          </div>
          <p className="mt-10 max-w-3xl font-mono text-[0.68rem] leading-relaxed tracking-[0.04em] text-muted-foreground">
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
      <ul className="space-y-2">
        {links.map((link) => (
          <li key={link}>
            <span className="text-sm text-muted-foreground">{link}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
