/** A small plotted line with one highlighted point: the product in one glyph. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true" className="shrink-0">
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
