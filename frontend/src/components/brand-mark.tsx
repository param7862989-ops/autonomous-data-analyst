/** A ticked figure on a ruled line: what the product does to every number it reports. */
export function BrandMark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" aria-hidden="true" className="shrink-0">
      <rect x="0.5" y="0.5" width="25" height="25" rx="2" fill="var(--color-surface)" />
      <rect x="0.5" y="0.5" width="25" height="25" rx="2" fill="none" stroke="var(--color-ink)" />
      {/* Highlighter swipe, fixed yellow in both themes so the mark reads the same. */}
      <rect x="4" y="11" width="18" height="7" fill="#ffe16a" />
      <path d="M4 20.5h18" stroke="var(--color-ink)" strokeWidth="1" />
      <path
        d="M8 14.5l3 3 7-9"
        fill="none"
        stroke="var(--color-primary)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
