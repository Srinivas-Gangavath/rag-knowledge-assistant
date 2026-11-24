import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { userFacingError } from "../services/errors";
import { LogoMark } from "../components/icons";
import { Button, Input, Toast } from "../components/ui";

export function AuthPage() {
  const { login, register, sessionExpired, clearSessionExpired } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    clearSessionExpired();
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, fullName);
      }
    } catch (err: unknown) {
      setError(userFacingError(err, "auth"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-slate-200/90 bg-white p-8 shadow-card">
        <div className="mb-6 text-center">
          <div className="flex justify-center mb-3">
            <LogoMark className="h-10 w-10" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Knowledge Assistant</h1>
          <p className="mt-1 text-xs text-slate-500">
            {mode === "login"
              ? "Sign in to access your organization workspaces"
              : "Create an account and set up your workspace"}
          </p>
        </div>

        <div className="mb-6 flex rounded-lg bg-slate-100 p-1">
          <button
            type="button"
            className={`flex-1 rounded-md py-1.5 text-xs font-semibold transition-colors ${
              mode === "login"
                ? "bg-white text-slate-900 shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Log in
          </button>
          <button
            type="button"
            className={`flex-1 rounded-md py-1.5 text-xs font-semibold transition-colors ${
              mode === "register"
                ? "bg-white text-slate-900 shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
            onClick={() => {
              setMode("register");
              setError(null);
            }}
          >
            Create account
          </button>
        </div>

        {sessionExpired && !error && (
          <div className="mb-4">
            <Toast
              type="warning"
              message="Your session has expired. Please sign in again."
              onClose={clearSessionExpired}
            />
          </div>
        )}

        {error && (
          <div className="mb-4">
            <Toast type="error" message={error} onClose={() => setError(null)} />
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "register" && (
            <Input
              id="auth-fullname"
              type="text"
              required
              label="Full Name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your name"
            />
          )}

          <Input
            id="auth-email"
            type="email"
            required
            label="Email Address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />

          <Input
            id="auth-password"
            type="password"
            required
            minLength={8}
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            helperText={mode === "register" ? "Must be at least 8 characters" : undefined}
          />

          <Button
            type="submit"
            variant="primary"
            size="lg"
            isLoading={submitting}
            className="w-full"
          >
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
      </div>
    </div>
  );
}
