import { BrandMark } from "@/components/brand-mark";
import { ThemeToggle } from "@/components/theme-toggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-start justify-center px-4 py-16 sm:items-center sm:py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5 font-semibold">
          <BrandMark />
          <span>Autonomous Data Analyst</span>
          <ThemeToggle className="ml-auto" />
        </div>
        {children}
      </div>
    </main>
  );
}
