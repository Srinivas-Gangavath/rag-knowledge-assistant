import type { AppView } from "./types";

const VIEW_PATHS: Record<AppView, string> = {
  dashboard: "/dashboard",
  documents: "/documents",
  assistant: "/assistant",
  settings: "/settings",
};

export function viewFromPath(pathname: string): AppView {
  const path = pathname.replace(/\/+$/, "") || "/dashboard";
  if (path === "/" || path === "/dashboard") {
    return "dashboard";
  }
  if (path === "/documents" || path.startsWith("/documents/")) {
    return "documents";
  }
  if (path === "/assistant" || path.startsWith("/assistant/")) {
    return "assistant";
  }
  if (path === "/settings" || path.startsWith("/settings/")) {
    return "settings";
  }
  return "dashboard";
}

export function pathForView(view: AppView): string {
  return VIEW_PATHS[view];
}
