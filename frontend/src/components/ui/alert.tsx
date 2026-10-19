import { clsx } from "clsx";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

type Tone = "info" | "success" | "warning" | "danger";

const tones: Record<Tone, { box: string; Icon: typeof Info }> = {
  info: { box: "border-primary/30 bg-primary-soft text-ink", Icon: Info },
  success: { box: "border-success/30 bg-success-soft text-ink", Icon: CheckCircle2 },
  warning: { box: "border-warning/30 bg-warning-soft text-ink", Icon: AlertTriangle },
  danger: { box: "border-danger/30 bg-danger-soft text-ink", Icon: XCircle },
};

const iconColor: Record<Tone, string> = {
  info: "text-primary",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const { box, Icon } = tones[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={clsx("flex gap-3 rounded-(--radius-panel) border px-4 py-3 text-sm", box, className)}
    >
      <Icon size={18} aria-hidden="true" className={clsx("mt-0.5 shrink-0", iconColor[tone])} />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={clsx(title && "mt-0.5", "text-ink/90")}>{children}</div> : null}
      </div>
      {action ? <div className="shrink-0 self-center">{action}</div> : null}
    </div>
  );
}
