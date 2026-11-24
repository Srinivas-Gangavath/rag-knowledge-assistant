import React, { forwardRef } from "react";

export type IconButtonVariant = "ghost" | "secondary" | "primary" | "danger";
export type IconButtonSize = "sm" | "md" | "lg";

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  "aria-label": string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  isLoading?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    {
      "aria-label": ariaLabel,
      variant = "ghost",
      size = "md",
      isLoading = false,
      className = "",
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    const sizeClasses = {
      sm: "h-8 w-8 p-1.5 text-xs",
      md: "h-9 w-9 p-2 text-sm",
      lg: "h-11 w-11 p-2.5 text-base",
    }[size];

    const variantClasses = {
      ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200/60",
      secondary:
        "border border-slate-200 bg-white text-slate-700 shadow-xs hover:bg-slate-50 hover:border-slate-300 hover:text-slate-900",
      primary: "bg-brand-600 text-white shadow-xs hover:bg-brand-700 active:bg-brand-800",
      danger:
        "border border-rose-200 bg-white text-rose-700 shadow-xs hover:bg-rose-50 hover:border-rose-300 hover:text-rose-800",
    }[variant];

    return (
      <button
        ref={ref}
        aria-label={ariaLabel}
        disabled={disabled || isLoading}
        className={`inline-flex shrink-0 items-center justify-center rounded-lg transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 active:scale-95 ${variantClasses} ${sizeClasses} ${className}`}
        {...props}
      >
        {isLoading ? (
          <svg
            className="h-4 w-4 animate-spin text-current"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
        ) : (
          children
        )}
      </button>
    );
  },
);

IconButton.displayName = "IconButton";
