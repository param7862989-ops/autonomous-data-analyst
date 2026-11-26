import { clsx } from "clsx";

/**
 * The working-paper layout. A page has a title block, then sections; each section's name sits
 * in a narrow margin column on the left and its content in the body column, as an auditor
 * notes a schedule's reference beside it. On phones the margin folds above the body.
 */
export function PageHeader({
  title,
  lead,
  back,
  actions,
  children,
}: {
  title: React.ReactNode;
  lead?: React.ReactNode;
  back?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="border-b border-ink pb-6">
      {back ? <div className="mb-4 text-sm">{back}</div> : null}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 max-w-[46rem]">
          <h1 className="text-[2rem] leading-[1.15] break-words sm:text-[2.375rem]">{title}</h1>
          {lead ? <div className="mt-3 max-w-[62ch] text-[16px] text-slate">{lead}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}

export function Section({
  label,
  id,
  note,
  children,
  className,
}: {
  /** The section's name, shown in the margin and used as its heading. */
  label: string;
  id: string;
  /** A short line under the name, in the margin. */
  note?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-labelledby={id}
      className={clsx(
        "grid gap-x-10 gap-y-3 border-b border-rule py-8 lg:grid-cols-[12rem_minmax(0,1fr)]",
        className,
      )}
    >
      <div>
        <h2 id={id} className="text-[1.1875rem] leading-snug">
          {label}
        </h2>
        {note ? <div className="mt-1 text-sm text-slate">{note}</div> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}
