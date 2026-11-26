import Link from "next/link";

import { OverviewCounts, RecentQuestions } from "@/components/overview-summary";
import { SystemStatus } from "@/components/system-status";
import { PageHeader, Section } from "@/components/ui/page";

const STEPS = [
  {
    title: "Upload a spreadsheet",
    body: "CSV or Excel, up to 25 MB. It is checked and cleaned on the way in.",
  },
  {
    title: "Read its profile",
    body: "Column types, missing values, distributions and warnings, before you ask anything.",
  },
  {
    title: "Ask in plain language",
    body: "The answer comes from computations run on your data. Each figure is checked against them, and each statement links to its table.",
  },
];

export default function OverviewPage() {
  return (
    <div>
      <PageHeader
        title="Overview"
        lead={<OverviewCounts />}
        actions={
          <Link
            href="/datasets"
            className="inline-flex h-10 items-center rounded-(--radius-control) bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
          >
            Upload a dataset
          </Link>
        }
      />

      <Section label="Recent questions" id="recent-heading" note={<Link href="/history" className="text-primary underline-offset-2 hover:underline">All history</Link>}>
        <RecentQuestions />
      </Section>

      <Section label="How it works" id="how-heading">
        <ol className="grid gap-x-8 gap-y-6 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="grid grid-cols-[1.75rem_1fr] gap-x-2">
              <span aria-hidden="true" className="font-serif text-[1.375rem] leading-none text-slate">
                {index + 1}
              </span>
              <div>
                <p className="font-medium">{step.title}</p>
                <p className="mt-1 text-sm text-slate">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section label="Service status" id="system-status-heading" className="border-b-0">
        <SystemStatus />
      </Section>
    </div>
  );
}
