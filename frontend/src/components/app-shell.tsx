"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { BrandMark } from "@/components/brand-mark";
import { ThemeToggle } from "@/components/theme-toggle";
import { useCurrentUser, useLogout } from "@/lib/auth/hooks";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/datasets", label: "Datasets" },
  { href: "/conversations", label: "Conversations" },
  { href: "/history", label: "History" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** A running head across the top, like the header line of a working paper, then the page. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-(--radius-control) focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex max-w-[78rem] flex-wrap items-center gap-x-3 gap-y-1 md:gap-x-8 px-4 pt-3 md:px-8 md:pt-0">
          <Link href="/" className="flex items-center gap-2.5 py-1 md:py-3.5">
            <BrandMark />
            <span className="font-serif text-[17px] font-semibold tracking-[-0.005em]">
              Autonomous Data Analyst
            </span>
          </Link>
          <ThemeToggle className="ml-auto md:order-last md:ml-0" />
          <nav aria-label="Main" className="order-last flex-1 md:order-none md:flex-none">
            <ul className="flex gap-x-2.5 sm:gap-x-4">
              {NAV_ITEMS.map(({ href, label }) => {
                const active = isActive(pathname, href);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "block border-b-2 py-2.5 text-sm whitespace-nowrap md:py-[1.1rem]",
                        active
                          ? "border-primary font-medium text-ink"
                          : "border-transparent text-slate hover:text-ink",
                      )}
                    >
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <AccountPanel />
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[78rem] min-w-0 px-4 pt-8 pb-16 md:px-8 md:pt-12">
        {children}
      </main>
    </div>
  );
}

function AccountPanel() {
  const user = useCurrentUser();
  const logout = useLogout();
  const router = useRouter();
  if (!user.data) return null;
  return (
    <div className="order-last flex min-w-0 items-center gap-3 text-sm md:order-none md:ml-auto">
      <span className="hidden min-w-0 max-w-56 truncate text-slate lg:inline" title={user.data.email}>
        {user.data.email}
      </span>
      <button
        type="button"
        onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
        disabled={logout.isPending}
        className="shrink-0 text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
      >
        Sign out
      </button>
    </div>
  );
}
