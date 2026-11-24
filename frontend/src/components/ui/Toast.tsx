import { IconButton } from "./IconButton";

export interface ToastProps {
  type?: "success" | "error" | "info" | "warning";
  title?: string;
  message: string;
  onClose?: () => void;
  className?: string;
}

export function Toast({
  type = "info",
  title,
  message,
  onClose,
  className = "",
}: ToastProps) {
  const typeConfig = {
    success: {
      wrapper: "border-emerald-200 bg-emerald-50/90 text-emerald-900",
      iconBg: "bg-emerald-100 text-emerald-600",
      titleColor: "text-emerald-950",
      textColor: "text-emerald-800",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      ),
    },
    error: {
      wrapper: "border-rose-200 bg-rose-50/90 text-rose-900",
      iconBg: "bg-rose-100 text-rose-600",
      titleColor: "text-rose-950",
      textColor: "text-rose-800",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      ),
    },
    warning: {
      wrapper: "border-amber-200 bg-amber-50/90 text-amber-900",
      iconBg: "bg-amber-100 text-amber-600",
      titleColor: "text-amber-950",
      textColor: "text-amber-800",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      ),
    },
    info: {
      wrapper: "border-slate-200 bg-white text-slate-800",
      iconBg: "bg-slate-100 text-slate-600",
      titleColor: "text-slate-900",
      textColor: "text-slate-600",
      icon: (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
  }[type];

  return (
    <div
      role={type === "error" ? "alert" : "status"}
      aria-live="polite"
      className={`flex items-start gap-3 rounded-xl border p-4 shadow-sm ${typeConfig.wrapper} ${className}`}
    >
      <div
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${typeConfig.iconBg}`}
        aria-hidden="true"
      >
        {typeConfig.icon}
      </div>
      <div className="flex-1 min-w-0">
        {title && <p className={`text-xs font-semibold ${typeConfig.titleColor}`}>{title}</p>}
        <p className={`text-xs leading-normal ${title ? "mt-0.5" : ""} ${typeConfig.textColor}`}>
          {message}
        </p>
      </div>
      {onClose && (
        <IconButton
          size="sm"
          variant="ghost"
          aria-label="Dismiss message"
          onClick={onClose}
          className="-mr-1.5 -mt-1.5"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      )}
    </div>
  );
}
