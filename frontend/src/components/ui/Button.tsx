import React, { forwardRef } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-solid";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  startIcon?: React.ReactNode;
  endIcon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      isLoading = false,
      startIcon,
      endIcon,
      className = "",
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    const sizeClasses = {
      sm: "btn-sm",
      md: "",
      lg: "btn-lg",
    }[size];

    const variantClasses = {
      primary: "btn-primary",
      secondary: "btn-secondary",
      ghost: "btn-ghost",
      danger: "btn-danger",
      "danger-solid": "btn-danger-solid",
    }[variant];

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={`${variantClasses} ${sizeClasses} ${className}`}
        {...props}
      >
        {isLoading && (
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
        )}
        {!isLoading && startIcon && (
          <span className="inline-flex shrink-0 items-center" aria-hidden="true">
            {startIcon}
          </span>
        )}
        <span>{children}</span>
        {!isLoading && endIcon && (
          <span className="inline-flex shrink-0 items-center" aria-hidden="true">
            {endIcon}
          </span>
        )}
      </button>
    );
  },
);

Button.displayName = "Button";
