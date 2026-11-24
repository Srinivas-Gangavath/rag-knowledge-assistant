import { useEffect, useState } from "react";

import { useAuth } from "./context/AuthContext";
import { AppLayout } from "./layouts/AppLayout";
import { pathForView, viewFromPath } from "./navigation";
import { AssistantPage } from "./pages/AssistantPage";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { WorkspaceSettingsPage } from "./pages/WorkspaceSettingsPage";
import type { AppView } from "./types";

const KNOWN_ROOTS = ["/", "/dashboard", "/documents", "/assistant", "/settings"];

export default function App() {
  const { user, isLoading } = useAuth();
  const [currentView, setCurrentView] = useState<AppView>(() =>
    viewFromPath(window.location.pathname),
  );

  useEffect(() => {
    const path = window.location.pathname.replace(/\/+$/, "") || "/";
    const isKnown =
      KNOWN_ROOTS.includes(path) ||
      path.startsWith("/settings/") ||
      path.startsWith("/documents/") ||
      path.startsWith("/assistant/");

    if (!isKnown) {
      window.history.replaceState({}, "", "/dashboard");
      setCurrentView("dashboard");
      return;
    }
    if (path === "/") {
      window.history.replaceState({}, "", "/dashboard");
    }
  }, []);

  useEffect(() => {
    function onPopState() {
      setCurrentView(viewFromPath(window.location.pathname));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Global non-conflicting keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (!user) return;

      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === "/") {
        const inputToFocus =
          document.getElementById("chat-composer-textarea") ||
          document.getElementById("document-search-input") ||
          document.getElementById("ws-member-search");
        if (inputToFocus) {
          event.preventDefault();
          inputToFocus.focus();
        }
      } else if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        navigate("assistant");
        setTimeout(() => {
          const newChatBtn = document.getElementById("new-conversation-btn");
          if (newChatBtn) {
            newChatBtn.click();
          }
          const composer = document.getElementById("chat-composer-textarea");
          if (composer) {
            composer.focus();
          }
        }, 50);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [user]);

  function navigate(view: AppView) {
    const path = pathForView(view);
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setCurrentView(view);
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="text-sm font-medium text-slate-500">Checking credentials...</div>
      </div>
    );
  }

  if (!user) {
    return <AuthPage />;
  }

  return (
    <AppLayout currentView={currentView} onNavigate={navigate}>
      {currentView === "dashboard" && <DashboardPage onNavigate={navigate} />}
      {currentView === "documents" && <DocumentsPage />}
      {currentView === "assistant" && <AssistantPage onNavigate={navigate} />}
      {currentView === "settings" && <WorkspaceSettingsPage />}
    </AppLayout>
  );
}
