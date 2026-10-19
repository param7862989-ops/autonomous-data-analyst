import { clsx } from "clsx";
import { forwardRef, useId } from "react";

export interface TextFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string | null;
}

/** A labelled input whose hint and error are announced by screen readers. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, className, id, ...props },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  return (
    <div className={className}>
      <label htmlFor={inputId} className="block text-sm font-medium">
        {label}
      </label>
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        className={clsx(
          "mt-1.5 block h-10 w-full rounded-(--radius-control) border bg-surface px-3 text-[15px]",
          "placeholder:text-slate/70 focus-visible:outline-2 focus-visible:outline-offset-0",
          error ? "border-danger" : "border-rule-strong",
        )}
        {...props}
      />
      {hint && !error ? (
        <p id={hintId} className="mt-1.5 text-sm text-slate">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
});
