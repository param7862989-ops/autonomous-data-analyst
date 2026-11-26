import { clsx } from "clsx";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

type Tone = "info" | "success" | "warning" | "danger";

const tones: Record<Tone, { box: string; Icon: typeof Info }> = {
  info: { box: "border-slate", Icon: Info },
  success: { box: "border-success", Icon: CheckCircle2 },
  warning: { box: "border-warning bg-warning-soft", Icon: AlertTriangle },
  danger: { box: "border-danger bg-danger-soft", Icon: XCircle },
};

const iconColor: Record<Tone, string> = {
  info: "text-slate",
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
      className={clsx("flex gap-3 border-l-2 py-2.5 pr-3 pl-3.5 text-sm text-ink", box, className)}
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
