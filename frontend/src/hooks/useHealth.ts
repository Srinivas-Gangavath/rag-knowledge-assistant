import { useEffect, useState } from "react";

import { api } from "../services/api";

type HealthState = {
  status: "loading" | "ok" | "error";
  message: string;
};

export function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>(() => {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      return { status: "error", message: "Connection unavailable" };
    }
    return { status: "loading", message: "Connecting…" };
  });

  useEffect(() => {
    let cancelled = false;

    function checkHealth() {
      if (typeof navigator !== "undefined" && !navigator.onLine) {
        setState({
          status: "error",
          message: "Connection unavailable",
        });
        return;
      }

      api
        .getHealth()
        .then((data) => {
          if (!cancelled) {
            setState({
              status: data.status === "ok" ? "ok" : "error",
              message: data.status === "ok" ? "Connected" : "Service error",
            });
          }
        })
        .catch(() => {
          if (!cancelled) {
            setState({
              status: "error",
              message: "Unavailable",
            });
          }
        });
    }

    checkHealth();

    function handleOnline() {
      checkHealth();
    }

    function handleOffline() {
      if (!cancelled) {
        setState({
          status: "error",
          message: "Connection unavailable",
        });
      }
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      cancelled = true;
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return state;
}
