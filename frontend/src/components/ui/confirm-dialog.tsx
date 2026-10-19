"use client";

import { useEffect, useId, useRef } from "react";

import { Button } from "./button";

/**
 * A modal confirmation built on the native <dialog> element, which provides focus trapping,
 * Escape to close, and an inert background.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  pending = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close?.();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-(--radius-panel) border border-rule bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/40"
    >
      {open ? (
        <div className="p-5">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <div className="mt-2 text-sm text-slate">{children}</div>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={onCancel} disabled={pending}>
              Cancel
            </Button>
            <Button variant="danger" onClick={onConfirm} pending={pending}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
