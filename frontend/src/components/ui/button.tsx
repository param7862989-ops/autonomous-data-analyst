import { clsx } from "clsx";
import { forwardRef } from "react";

import { Spinner } from "./spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary: "bg-primary text-white hover:bg-primary-hover disabled:bg-primary/50",
  secondary:
    "border border-rule-strong bg-surface text-ink hover:border-slate disabled:text-slate/70",
  ghost: "text-ink hover:bg-primary-soft disabled:text-slate/70",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:bg-danger/50",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-[15px] gap-2",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a spinner and disables the button while an action is in flight. */
  pending?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", pending = false, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center rounded-(--radius-control) font-medium",
        "transition-colors disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      {...props}
    >
      {pending ? <Spinner size={14} label="" /> : null}
      {children}
    </button>
  );
});
