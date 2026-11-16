"use client";

import { clsx } from "clsx";
import { Monitor, Moon, Sun } from "lucide-react";

import { type ThemePreference, useTheme } from "@/lib/theme";

const OPTIONS = [
  { value: "system", label: "System theme", Icon: Monitor },
  { value: "light", label: "Light theme", Icon: Sun },
  { value: "dark", label: "Dark theme", Icon: Moon },
] as const satisfies ReadonlyArray<{ value: ThemePreference; label: string; Icon: unknown }>;

/** Three-way theme switch: follow the system, or force light or dark. */
export function ThemeToggle({ className }: { className?: string }) {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="group"
      aria-label="Colour theme"
      className={clsx(
        "inline-flex rounded-(--radius-control) border border-rule bg-paper p-0.5",
        className,
      )}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={active}
            title={label}
            onClick={() => setPreference(value)}
            className={clsx(
              "flex size-7 items-center justify-center rounded-[3px]",
              active ? "bg-surface text-ink shadow-sm" : "text-slate hover:text-ink",
            )}
          >
            <Icon size={14} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
