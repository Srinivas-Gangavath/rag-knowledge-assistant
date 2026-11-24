import { useAuth } from "../context/AuthContext";
import { MenuIcon, ChevronDownIcon } from "./icons";
import {
  Dropdown,
  DropdownItem,
  DropdownHeader,
  DropdownDivider,
  Tooltip,
  Badge,
} from "./ui";
import type { AppView } from "../types";
import { formatRole, getInitials, getUserDisplayName } from "../utils/format";

type HeaderProps = {
  title: string;
  healthLabel: string;
  healthStatus: "loading" | "ok" | "error";
  onOpenNavigation: () => void;
  onNavigate?: (view: AppView) => void;
};

const VIEW_TITLES: Record<AppView, string> = {
  dashboard: "Dashboard",
  documents: "Documents",
  assistant: "Assistant",
  settings: "Settings",
};

export function getViewTitle(view: AppView): string {
  return VIEW_TITLES[view];
}

export function Header({
  title,
  healthLabel,
  healthStatus,
  onOpenNavigation,
  onNavigate,
}: HeaderProps) {
  const { user, activeWorkspace, logout } = useAuth();

  const statusDotClass =
    healthStatus === "ok"
      ? "bg-emerald-500"
      : healthStatus === "loading"
        ? "bg-amber-500 animate-pulse"
        : "bg-rose-500";

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-200/80 bg-white px-4 sm:px-6 z-20">
      {/* Left: Mobile hamburger & Page Title */}
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          className="btn-secondary h-9 w-9 p-0 lg:hidden shrink-0"
          onClick={onOpenNavigation}
          aria-label="Open navigation menu"
        >
          <MenuIcon className="h-5 w-5" />
        </button>
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold tracking-tight text-slate-900 sm:text-lg">
            {title}
          </h1>
        </div>
      </div>

      {/* Right: Service Status & Dynamic Account Menu */}
      <div className="flex items-center gap-3">
        {/* Subtle Service Status Pill */}
        <Tooltip title={`Service status: ${healthLabel}`} placement="bottom">
          <div
            className="hidden items-center gap-2 rounded-full border border-slate-200/90 bg-slate-50 px-3 py-1 sm:flex select-none"
            role="status"
            aria-live="polite"
          >
            <span className={`h-2 w-2 rounded-full ${statusDotClass}`} aria-hidden="true" />
            <span className="text-xs font-medium text-slate-600">{healthLabel}</span>
          </div>
        </Tooltip>

        {/* Dynamic Account Dropdown */}
        {user ? (
          <Dropdown
            align="right"
            width="w-64"
            trigger={({ isOpen, toggle, ref }) => (
              <button
                ref={ref}
                type="button"
                onClick={toggle}
                className={`flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5 transition-colors hover:bg-slate-50 hover:border-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                  isOpen ? "bg-slate-50 border-slate-300" : ""
                }`}
                aria-label="User account menu"
                aria-expanded={isOpen}
                aria-haspopup="menu"
              >
                <span
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700 ring-1 ring-brand-200"
                  aria-hidden="true"
                >
                  {getInitials(user)}
                </span>
                <span className="hidden max-w-[130px] truncate text-left text-xs font-semibold text-slate-800 md:inline">
                  {getUserDisplayName(user)}
                </span>
                <ChevronDownIcon
                  className={`hidden h-3.5 w-3.5 text-slate-400 transition-transform md:inline ${
                    isOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
            )}
          >
            {({ close }) => (
              <div>
                <DropdownHeader>
                  <p className="truncate text-xs font-semibold text-slate-900">
                    {getUserDisplayName(user)}
                  </p>
                  <p className="truncate text-[11px] font-normal text-slate-500 mt-0.5">
                    {user.email}
                  </p>
                  {activeWorkspace && (
                    <div className="mt-2.5 flex items-center justify-between rounded-lg border border-slate-200/80 bg-slate-50/80 p-2">
                      <span className="truncate text-[11px] font-medium text-slate-700">
                        {activeWorkspace.name}
                      </span>
                      <Badge variant="brand" size="sm">
                        {formatRole(activeWorkspace.role)}
                      </Badge>
                    </div>
                  )}
                </DropdownHeader>

                <DropdownDivider />

                <div className="px-1 py-0.5 space-y-0.5">
                  <DropdownItem
                    onClick={() => {
                      close();
                      if (onNavigate) {
                        onNavigate("settings");
                      }
                      window.history.pushState({}, "", "/settings?section=account");
                      window.dispatchEvent(new PopStateEvent("popstate"));
                    }}
                  >
                    <svg
                      className="h-3.5 w-3.5 text-slate-500"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
                      />
                    </svg>
                    <span>Profile & Identity</span>
                  </DropdownItem>

                  <DropdownItem
                    variant="danger"
                    onClick={() => {
                      close();
                      logout();
                    }}
                  >
                    <svg
                      className="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9"
                      />
                    </svg>
                    <span>Sign out</span>
                  </DropdownItem>
                </div>
              </div>
            )}
          </Dropdown>
        ) : (
          <div
            className="flex items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-500"
            aria-label="Account status"
          >
            <span>Account</span>
          </div>
        )}
      </div>
    </header>
  );
}
