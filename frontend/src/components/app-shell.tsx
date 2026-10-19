"use client";

import { clsx } from "clsx";
import { LayoutGrid } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [{ href: "/", label: "Overview", Icon: LayoutGrid }] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[232px_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-(--radius-control) focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule bg-surface md:min-h-dvh md:border-r md:border-b-0">
        <div className="flex items-center gap-2.5 px-4 py-4 md:px-5 md:py-6">
          <BrandMark />
          <span className="text-[15px] font-semibold leading-tight">
            Autonomous
            <br className="hidden md:block" /> Data Analyst
          </span>
        </div>
        <nav aria-label="Main" className="px-2 pb-3 md:px-3">
          <ul className="flex gap-1 md:flex-col">
            {NAV_ITEMS.map(({ href, label, Icon }) => {
              const active = isActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "flex items-center gap-2.5 rounded-(--radius-control) px-3 py-2 text-sm",
                      active
                        ? "bg-primary-soft font-medium text-primary"
                        : "text-slate hover:bg-paper hover:text-ink",
                    )}
                  >
                    <Icon size={16} aria-hidden="true" />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>
      <main id="main" className="min-w-0 px-4 py-6 md:px-10 md:py-10">
        {children}
      </main>
    </div>
  );
}

/** A small plotted line with one highlighted point: the product in one glyph. */
function BrandMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" className="shrink-0">
      <rect width="28" height="28" rx="5" fill="var(--color-ink)" />
      <path
        d="M5 19.5 L10.5 14 L14.5 17 L22.5 8.5"
        stroke="white"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="14.5" cy="17" r="3" fill="var(--color-highlight)" />
    </svg>
  );
}
