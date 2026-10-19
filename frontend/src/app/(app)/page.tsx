import { SystemStatus } from "@/components/system-status";

const STEPS = [
  {
    title: "Upload a dataset",
    body: "CSV or Excel. Files are validated, cleaned of duplicate column names, and profiled.",
  },
  {
    title: "Review the profile",
    body: "Column types, missing values, distributions and data-quality warnings, before any question is asked.",
  },
  {
    title: "Ask a question",
    body: "The analyst plans the analysis, runs real computations on your data, and cites the results behind every figure.",
  },
];

export default function OverviewPage() {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
      <p className="mt-2 max-w-[65ch] text-slate">
        Ask questions about your data in plain language. Every number in an answer comes from a
        computation you can inspect.
      </p>

      <section aria-labelledby="how-heading" className="mt-10">
        <h2 id="how-heading" className="text-base font-semibold">
          How it works
        </h2>
        <ol className="mt-4 grid gap-6 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="border-t-2 border-ink pt-3">
              <span className="tabular text-sm text-slate">Step {index + 1}</span>
              <p className="mt-1 font-medium">{step.title}</p>
              <p className="mt-1 text-sm text-slate">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <div className="mt-12">
        <SystemStatus />
      </div>
    </div>
  );
}
