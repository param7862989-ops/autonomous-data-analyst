"use client";

import { clsx } from "clsx";
import { Database, LayoutGrid, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { BrandMark } from "@/components/brand-mark";
import { useCurrentUser, useLogout } from "@/lib/auth/hooks";

const NAV_ITEMS = [
  { href: "/", label: "Overview", Icon: LayoutGrid },
  { href: "/datasets", label: "Datasets", Icon: Database },
] as const;

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
      <header className="flex flex-col border-b border-rule bg-surface md:sticky md:top-0 md:h-dvh md:border-r md:border-b-0">
        <div className="flex items-center gap-2.5 px-4 py-4 md:px-5 md:py-6">
          <BrandMark />
          <span className="text-[15px] font-semibold leading-tight">
            Autonomous
            <br className="hidden md:block" /> Data Analyst
          </span>
        </div>
        <nav aria-label="Main" className="px-2 pb-3 md:flex-1 md:px-3">
          <ul className="flex gap-1 overflow-x-auto md:flex-col">
            {NAV_ITEMS.map(({ href, label, Icon }) => {
              const active = isActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "flex items-center gap-2.5 whitespace-nowrap rounded-(--radius-control) px-3 py-2 text-sm",
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
        <AccountPanel />
      </header>
      <main id="main" className="min-w-0 px-4 py-6 md:px-10 md:py-10">
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
    <div className="flex items-center justify-between gap-2 border-t border-rule px-4 py-3 md:px-5">
      <span className="min-w-0 truncate text-sm text-slate" title={user.data.email}>
        {user.data.email}
      </span>
      <button
        type="button"
        onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
        disabled={logout.isPending}
        className="flex shrink-0 items-center gap-1.5 rounded-(--radius-control) px-2 py-1.5 text-sm text-slate hover:bg-paper hover:text-ink"
      >
        <LogOut size={15} aria-hidden="true" />
        Sign out
      </button>
    </div>
  );
}
