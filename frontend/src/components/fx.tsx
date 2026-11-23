/**
 * Motion & effects layer (Aceternity-style components built on motion + GSAP, themed by our tokens).
 * Everything respects `prefers-reduced-motion`.
 */
import { useGSAP } from "@gsap/react";
import clsx from "clsx";
import gsap from "gsap";
import { motion, useMotionTemplate, useMotionValue, useReducedMotion } from "motion/react";
import { useRef, type ComponentProps, type MouseEvent, type ReactNode } from "react";

gsap.registerPlugin(useGSAP);

/** Dotted grid that fades out radially (Aceternity "dot background"). */
export function DotBackdrop({ className }: { className?: string }) {
  return (
    <div aria-hidden className={clsx("pointer-events-none absolute inset-0 -z-10", className)}
      style={{
        backgroundImage: "radial-gradient(color-mix(in oklab, var(--c-ink) 14%, transparent) 1px, transparent 1px)",
        backgroundSize: "22px 22px",
        maskImage: "radial-gradient(ellipse 70% 60% at 50% 30%, #000 40%, transparent 100%)",
        WebkitMaskImage: "radial-gradient(ellipse 70% 60% at 50% 30%, #000 40%, transparent 100%)",
      }} />
  );
}

/** Soft animated brand spotlight behind a hero (Aceternity "spotlight"). */
export function Spotlight({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div aria-hidden className={clsx("pointer-events-none absolute -z-10 rounded-full blur-3xl", className)}
      style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--c-brand) 32%, transparent), transparent)" }}
      initial={{ opacity: 0, scale: 0.8 }}
      animate={reduce ? { opacity: 1 } : { opacity: [0.55, 0.9, 0.55], scale: [0.95, 1.05, 0.95] }}
      transition={reduce ? { duration: 0.3 } : { duration: 9, repeat: Infinity, ease: "easeInOut" }} />
  );
}

/** Card whose border glows where the cursor is (Aceternity "card spotlight"). */
export function GlowCard({ children, className, active, ...rest }: ComponentProps<"div"> & { active?: boolean }) {
  const x = useMotionValue(-200);
  const y = useMotionValue(-200);
  const glow = useMotionTemplate`radial-gradient(240px circle at ${x}px ${y}px, color-mix(in oklab, var(--c-brand) 22%, transparent), transparent 70%)`;
  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    x.set(e.clientX - r.left);
    y.set(e.clientY - r.top);
  };
  return (
    <div {...rest} onMouseMove={onMove} onMouseLeave={() => { x.set(-200); y.set(-200); }}
      className={clsx("group relative overflow-hidden rounded-xl border bg-card p-4 shadow-sm transition-shadow hover:shadow-md",
        active ? "border-brand ring-2 ring-brand/30" : "border-border", className)}>
      <motion.div aria-hidden className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100" style={{ background: glow }} />
      <div className="relative">{children}</div>
    </div>
  );
}

/** Primary call to action with a moving sheen (Aceternity "shimmer button"). */
export function ShimmerButton({ children, className, ...rest }: ComponentProps<"button">) {
  return (
    <button {...rest} className={clsx(
      "relative inline-flex items-center justify-center gap-2 overflow-hidden rounded-xl border border-brand px-5 py-2.5 font-medium text-white shadow-[0_8px_30px_-10px] shadow-brand/60 transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
      "bg-[linear-gradient(110deg,var(--c-brand),45%,color-mix(in_oklab,var(--c-brand)_60%,white),55%,var(--c-brand))] bg-[length:200%_100%] animate-shimmer",
      className)}>
      {children}
    </button>
  );
}

/** Words appear one after another, de-blurring (Aceternity "text generate effect"). */
export function TextGenerate({ text, className }: { text: string; className?: string }) {
  const reduce = useReducedMotion();
  const words = text.split(" ");
  return (
    <p className={className}>
      {words.map((w, i) => (
        <motion.span key={`${i}-${w}`} className="inline-block"
          initial={reduce ? false : { opacity: 0, filter: "blur(6px)" }} animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.25, delay: Math.min(i * 0.035, 1.2) }}>{w}&nbsp;</motion.span>
      ))}
    </p>
  );
}

/** Number that counts up with GSAP whenever its value changes. */
export function NumberTicker({ value, decimals = 0, className }: { value: number; decimals?: number; className?: string }) {
  const el = useRef<HTMLSpanElement>(null);
  const prev = useRef(0);
  useGSAP(() => {
    const node = el.current;
    if (!node) return;
    const fmt = (v: number) => v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { node.textContent = fmt(value); prev.current = value; return; }
    const o = { v: prev.current };
    gsap.to(o, { v: value, duration: 0.9, ease: "power3.out", onUpdate: () => { node.textContent = fmt(o.v); } });
    prev.current = value;
  }, { dependencies: [value, decimals] });
  return <span ref={el} className={clsx("tabular-nums", className)}>0</span>;
}

/** GSAP stagger-in for every `[data-reveal]` child of the container, re-run when `deps` change. */
export function Reveal({ children, deps = [], className }: { children: ReactNode; deps?: unknown[]; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    gsap.from("[data-reveal]", { y: 14, opacity: 0, duration: 0.45, ease: "power2.out", stagger: 0.05, clearProps: "all" });
  }, { scope: box, dependencies: deps });
  return <div ref={box} className={className}>{children}</div>;
}

/** Route transition wrapper. */
export function Page({ children }: { children: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22, ease: "easeOut" }}>
      {children}
    </motion.div>
  );
}
