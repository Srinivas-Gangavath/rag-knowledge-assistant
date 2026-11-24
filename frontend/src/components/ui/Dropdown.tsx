import React, { useEffect, useRef, useState } from "react";

export interface DropdownProps {
  trigger: (props: {
    isOpen: boolean;
    toggle: () => void;
    ref: React.RefObject<HTMLButtonElement>;
  }) => React.ReactNode;
  align?: "left" | "right";
  width?: string;
  className?: string;
  children: (props: { close: () => void }) => React.ReactNode;
}

export function Dropdown({
  trigger,
  align = "right",
  width = "w-56",
  className = "",
  children,
}: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && isOpen) {
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const toggle = () => setIsOpen((prev) => !prev);
  const close = () => setIsOpen(false);

  return (
    <div className="relative inline-block text-left" ref={containerRef}>
      {trigger({ isOpen, toggle, ref: buttonRef })}

      {isOpen && (
        <div
          role="menu"
          aria-orientation="vertical"
          tabIndex={-1}
          className={`absolute ${
            align === "right" ? "right-0" : "left-0"
          } mt-1.5 ${width} z-50 rounded-xl border border-slate-200/90 bg-white py-1.5 shadow-dropdown animate-in fade-in zoom-in-95 duration-100 ${className}`}
        >
          {children({ close })}
        </div>
      )}
    </div>
  );
}

export function DropdownItem({
  onClick,
  variant = "default",
  className = "",
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "danger";
}) {
  const variantClasses =
    variant === "danger"
      ? "text-rose-600 hover:bg-rose-50 hover:text-rose-700"
      : "text-slate-700 hover:bg-slate-50 hover:text-slate-900";

  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2 px-3.5 py-2 text-left text-xs font-medium transition-colors ${variantClasses} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function DropdownHeader({
  className = "",
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`border-b border-slate-100 px-3.5 py-2 text-xs font-semibold text-slate-900 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function DropdownDivider({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="separator"
      className={`my-1 h-px bg-slate-100 ${className}`}
      {...props}
    />
  );
}
