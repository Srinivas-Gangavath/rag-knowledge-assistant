import { useAuth } from "../context/AuthContext";
import { NAV_ITEMS, LogoMark, ChevronDownIcon } from "./icons";
import { Badge, Tooltip } from "./ui";
import type { AppView } from "../types";

type SidebarProps = {
  currentView: AppView;
  onNavigate: (view: AppView) => void;
  onNavigateAndClose?: (view: AppView) => void;
};

export function Sidebar({
  currentView,
  onNavigate,
  onNavigateAndClose,
}: SidebarProps) {
  const {
    user,
    activeWorkspace,
    availableWorkspaces,
    setActiveWorkspace,
    isWorkspaceAdmin,
  } = useAuth();

  function handleSelect(view: AppView) {
    if (onNavigateAndClose) {
      onNavigateAndClose(view);
      return;
    }
    onNavigate(view);
  }

  return (
    <div className="flex h-full flex-col bg-white select-none">
      {/* Brand Identity Area */}
      <div className="flex items-center gap-3 border-b border-slate-200/80 px-5 py-4">
        <LogoMark className="h-8 w-8 shrink-0" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight text-slate-900">
            Knowledge Assistant
          </p>
          <p className="truncate text-[11px] font-medium text-slate-500">
            AI Knowledge Platform
          </p>
        </div>
      </div>

      {/* Workspace Switcher */}
      {user && availableWorkspaces.length > 0 && (
        <div className="border-b border-slate-200/70 bg-slate-50/60 px-4 py-3">
          <label
            htmlFor="workspace-switcher"
            className="block text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1"
          >
            Workspace
          </label>
          <div className="relative">
            <select
              id="workspace-switcher"
              value={activeWorkspace?.id || ""}
              onChange={(e) => {
                const target = availableWorkspaces.find((w) => w.id === e.target.value);
                if (target) {
                  setActiveWorkspace(target);
                }
              }}
              className="w-full appearance-none rounded-lg border border-slate-200 bg-white py-1.5 pl-3 pr-8 text-xs font-medium text-slate-800 shadow-xs transition-colors hover:border-slate-300 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            >
              {availableWorkspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-slate-400">
              <ChevronDownIcon className="h-3.5 w-3.5" />
            </div>
          </div>
        </div>
      )}

      {/* Core Navigation Items */}
      <nav className="flex-1 space-y-1 p-3" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => {
          const active = item.id === currentView;
          const classes = [
            "nav-item",
            active ? "nav-item-active" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <Tooltip key={item.id} title={item.description} placement="right">
              <button
                type="button"
                className={classes}
                onClick={() => handleSelect(item.id)}
                aria-current={active ? "page" : undefined}
              >
                <item.icon className={`h-5 w-5 shrink-0 ${active ? "text-brand-600" : "text-slate-500"}`} />
                <span className="flex-1 text-left">{item.label}</span>
                {item.id === "settings" && isWorkspaceAdmin && (
                  <Badge variant="brand" size="sm" className="ml-auto">
                    Admin
                  </Badge>
                )}
              </button>
            </Tooltip>
          );
        })}
      </nav>
    </div>
  );
}
