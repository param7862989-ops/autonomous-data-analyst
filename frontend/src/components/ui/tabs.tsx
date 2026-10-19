"use client";

import { clsx } from "clsx";
import { useId, useRef } from "react";

export type Tab = { id: string; label: string; content: React.ReactNode };

/** WAI-ARIA tabs: arrow keys move between tabs, only the active tab is in the tab order. */
export function Tabs({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  label: string;
}) {
  const baseId = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const last = tabs.length - 1;
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % tabs.length
        : event.key === "ArrowLeft"
          ? (index - 1 + tabs.length) % tabs.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].id);
    buttons.current[next]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 border-b border-rule">
        {tabs.map((tab, index) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              ref={(element) => {
                buttons.current[index] = element;
              }}
              role="tab"
              type="button"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={clsx(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
                selected
                  ? "border-ink text-ink"
                  : "border-transparent text-slate hover:text-ink",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      {tabs.map((tab) =>
        tab.id === active ? (
          <div
            key={tab.id}
            role="tabpanel"
            id={`${baseId}-panel-${tab.id}`}
            aria-labelledby={`${baseId}-tab-${tab.id}`}
            className="pt-6"
          >
            {tab.content}
          </div>
        ) : null,
      )}
    </div>
  );
}
