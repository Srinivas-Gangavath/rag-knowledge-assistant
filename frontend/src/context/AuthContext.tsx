import React, { createContext, useContext, useEffect, useState } from "react";
import { api, setActiveWorkspaceId, setAuthToken, setOnAuthExpired } from "../services/api";
import { clearSourceEvidenceCache } from "../components/chat/SourceDrawer";
import type { User, UserWorkspace } from "../types";

type AuthContextType = {
  user: User | null;
  isLoading: boolean;
  sessionExpired: boolean;
  clearSessionExpired: () => void;
  activeWorkspace: UserWorkspace | null;
  availableWorkspaces: UserWorkspace[];
  setActiveWorkspace: (ws: UserWorkspace) => void;
  refreshWorkspaces: () => Promise<void>;
  isWorkspaceAdmin: boolean;
  canUpload: boolean;
  canDelete: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState<boolean>(false);
  const [activeWorkspace, setActiveWorkspaceState] = useState<UserWorkspace | null>(null);
  const [availableWorkspaces, setAvailableWorkspaces] = useState<UserWorkspace[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  function setActiveWorkspace(ws: UserWorkspace) {
    clearSourceEvidenceCache();
    setActiveWorkspaceState(ws);
    setActiveWorkspaceId(ws.id);
    try {
      localStorage.setItem("preferred_workspace_id", ws.id);
    } catch {
      // ignore localStorage errors
    }
  }

  async function loadWorkspaces(preferredId?: string | null): Promise<UserWorkspace[]> {
    try {
      const res = await api.listWorkspaces();
      const list: UserWorkspace[] = res.workspaces.map((w) => ({
        id: w.id,
        organization_id: w.organization_id,
        name: w.name,
        slug: w.slug,
        role: w.role || "VIEWER",
      }));
      setAvailableWorkspaces(list);

      const targetId = preferredId || localStorage.getItem("preferred_workspace_id");
      const match = list.find((w) => w.id === targetId);
      if (match) {
        setActiveWorkspace(match);
      } else if (list.length > 0) {
        setActiveWorkspace(list[0]);
      }
      return list;
    } catch {
      return [];
    }
  }

  async function refreshWorkspaces() {
    await loadWorkspaces(activeWorkspace?.id);
  }

  // Attempt initial session restore via HTTP-only refresh cookie
  useEffect(() => {
    setOnAuthExpired(() => {
      clearSourceEvidenceCache();
      setUser(null);
      setSessionExpired(true);
      setActiveWorkspaceState(null);
      setAvailableWorkspaces([]);
    });

    let mounted = true;
    async function restoreSession() {
      try {
        await api.refresh();
        const me = await api.getMe();
        if (mounted) {
          setUser(me);
          setSessionExpired(false);
          await loadWorkspaces();
        }
      } catch {
        if (mounted) {
          clearSourceEvidenceCache();
          setUser(null);
          setActiveWorkspaceState(null);
          setAvailableWorkspaces([]);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    restoreSession();
    return () => {
      mounted = false;
      setOnAuthExpired(null);
    };
  }, []);

  async function login(email: string, password: string) {
    clearSourceEvidenceCache();
    setSessionExpired(false);
    const authRes = await api.login(email, password);
    setAuthToken(authRes.access_token);
    const me = await api.getMe();
    setUser(me);
    await loadWorkspaces();
  }

  async function register(email: string, password: string, fullName: string) {
    clearSourceEvidenceCache();
    setSessionExpired(false);
    const authRes = await api.register(email, password, fullName);
    setAuthToken(authRes.access_token);
    const me = await api.getMe();
    setUser(me);
    await loadWorkspaces();
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      clearSourceEvidenceCache();
      setUser(null);
      setSessionExpired(false);
      setActiveWorkspaceState(null);
      setAvailableWorkspaces([]);
      setActiveWorkspaceId(null);
    }
  }

  const isOrgOwner = user?.organizations?.some((o) => o.role === "OWNER") ?? false;
  const isWorkspaceAdmin = activeWorkspace?.role === "WORKSPACE_ADMIN" || isOrgOwner;
  const canUpload = isWorkspaceAdmin || activeWorkspace?.role === "CONTRIBUTOR";
  const canDelete = isWorkspaceAdmin;

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        sessionExpired,
        clearSessionExpired: () => setSessionExpired(false),
        activeWorkspace,
        availableWorkspaces,
        setActiveWorkspace,
        refreshWorkspaces,
        isWorkspaceAdmin,
        canUpload,
        canDelete,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
