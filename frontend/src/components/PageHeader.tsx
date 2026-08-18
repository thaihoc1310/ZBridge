import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, highlight, description, action }: { eyebrow: string; title: string; highlight?: string; description?: string; action?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end">
      <div>
        <span className="eyebrow"><span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />{eyebrow}</span>
        <h1 className="mt-4 font-display text-3xl leading-tight text-foreground sm:text-4xl">{title} {highlight && <span className="gradient-text">{highlight}</span>}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
  );
}

