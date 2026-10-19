import { CalendarDays, Hash, ToggleLeft, Tags, Type } from "lucide-react";

import type { SemanticType } from "@/lib/datasets/api";

const TYPES: Record<SemanticType, { label: string; Icon: typeof Hash }> = {
  numeric: { label: "Number", Icon: Hash },
  datetime: { label: "Date", Icon: CalendarDays },
  categorical: { label: "Category", Icon: Tags },
  boolean: { label: "True/false", Icon: ToggleLeft },
  text: { label: "Text", Icon: Type },
};

export function TypeBadge({ type }: { type: SemanticType }) {
  const { label, Icon } = TYPES[type];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-slate">
      <Icon size={14} aria-hidden="true" />
      {label}
    </span>
  );
}
