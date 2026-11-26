import { BrandMark } from "@/components/brand-mark";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Sign-in and sign-up: what the product does on the left, the form on a sheet to the right.
 * The example sentence shows the one idea the product is built on, a figure ticked against
 * the computation behind it.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[72rem] flex-col px-4 md:px-8">
      <div className="flex items-center gap-2.5 py-5">
        <BrandMark />
        <span className="font-serif text-[17px] font-semibold">Autonomous Data Analyst</span>
        <ThemeToggle className="ml-auto" />
      </div>
      <div className="grid flex-1 items-start gap-10 border-t border-ink pt-10 pb-16 md:grid-cols-[minmax(0,1fr)_24rem] md:gap-16 md:pt-16">
        <section aria-label="About this app" className="max-w-[34rem]">
          <p className="font-serif text-[1.75rem] leading-[1.25] font-semibold sm:text-[2.25rem]">
            Ask a question about your spreadsheet. Get an answer whose figures you can check.
          </p>
          <p className="mt-5 max-w-[52ch] text-[16px] text-slate">
            Each figure in an answer is matched against a computation on your data. Matching
            figures are highlighted, and every statement links to the table it came from.
          </p>
          <figure className="mt-8 border-l-2 border-ink pl-4">
            <blockquote className="font-serif text-[17px] leading-relaxed">
              Revenue fell from <mark className="ticked bg-highlight/70 px-0.5 text-ink">$758,989</mark>{" "}
              in Q2 to <mark className="ticked bg-highlight/70 px-0.5 text-ink">$497,231</mark> in
              Q3. West accounts for <mark className="ticked bg-highlight/70 px-0.5 text-ink">60.3%</mark>{" "}
              of the drop.
            </blockquote>
            <figcaption className="mt-2 text-sm text-slate">
              From an answer about the sample sales data included with the app.
            </figcaption>
          </figure>
        </section>
        <main className="border border-rule bg-surface p-6 sm:p-8">{children}</main>
      </div>
    </div>
  );
}
