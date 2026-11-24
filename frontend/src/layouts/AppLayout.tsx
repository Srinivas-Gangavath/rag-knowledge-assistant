import { useState, type ReactNode } from "react";

import { Header, getViewTitle } from "../components/Header";
import { MobileNav } from "../components/MobileNav";
import { Sidebar } from "../components/Sidebar";
import { useHealth } from "../hooks/useHealth";
import type { AppView } from "../types";

type AppLayoutProps = {
  currentView: AppView;
  onNavigate: (view: AppView) => void;
  children: ReactNode;
};

export function AppLayout({ currentView, onNavigate, children }: AppLayoutProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const health = useHealth();

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-50 font-sans antialiased text-slate-900">
      {/* Accessible skip link */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {/* Desktop Persistent Sidebar */}
      <aside
        className="hidden w-64 shrink-0 border-r border-slate-200/80 bg-white lg:flex lg:flex-col h-full z-10"
        aria-label="Sidebar navigation"
      >
        <Sidebar currentView={currentView} onNavigate={onNavigate} />
      </aside>

      {/* Mobile Drawer */}
      <MobileNav
        open={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        currentView={currentView}
        onNavigate={onNavigate}
      />

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
        <Header
          title={getViewTitle(currentView)}
          healthLabel={health.message}
          healthStatus={health.status}
          onOpenNavigation={() => setMobileNavOpen(true)}
          onNavigate={onNavigate}
        />
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 overflow-y-auto px-4 py-6 sm:px-6 sm:py-8 lg:px-8 focus:outline-none"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
