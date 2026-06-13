import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiConfig, isDevMode } from "../config/authConfig";
import { getAuthToken } from "../services/apiClient";

export type LiveWatchStatus = "connecting" | "live" | "reconnecting" | "offline";

export interface AksLiveWatchOptions {
  clusterId?: string | null;
  namespace?: string;
  resources: string[];
  enabled?: boolean;
}

const RESOURCE_QUERY_KEYS: Record<string, string[]> = {
  clusters: ["aks-clusters-cached", "aks-clusters"],
  nodepools: ["aks-nodepools-cached", "aks-nodepools"],
  deployments: ["aks-deployments-cached", "aks-deployments"],
  pods: ["aks-pod-metrics"],
  cronjobs: ["aks-cronjobs-cached", "aks-cronjobs"],
  secrets: ["aks-secrets-cached"],
  services: ["aks-services-cached"],
  configmaps: ["aks-configmaps-cached"],
  ingress: ["aks-ingress-cached"],
  helm: ["aks-helm-releases"],
};

function buildWsUrl(token: string | null): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const apiPath = apiConfig.baseUrl.startsWith("http")
    ? apiConfig.baseUrl.replace(/^http/, "ws")
    : `${proto}//${window.location.host}${apiConfig.baseUrl}`;
  const url = `${apiPath}/aks/watch`;
  if (token) {
    return `${url}?access_token=${encodeURIComponent(token)}`;
  }
  return url;
}

export function useAksLiveWatch({
  clusterId,
  namespace,
  resources,
  enabled = true,
}: AksLiveWatchOptions) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const [status, setStatus] = useState<LiveWatchStatus>("offline");
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);

  const invalidateForResource = useCallback(
    (resourceType: string) => {
      const keys = RESOURCE_QUERY_KEYS[resourceType] || [];
      keys.forEach((key) => {
        if (clusterId) {
          queryClient.invalidateQueries({ queryKey: [key, clusterId] });
        } else {
          queryClient.invalidateQueries({ queryKey: [key] });
        }
      });
    },
    [clusterId, queryClient]
  );

  useEffect(() => {
    if (!enabled || resources.length === 0) {
      setStatus("offline");
      return;
    }

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = async () => {
      if (cancelled) return;
      setStatus(retryRef.current > 0 ? "reconnecting" : "connecting");
      const token = isDevMode ? null : await getAuthToken();
      const ws = new WebSocket(buildWsUrl(token));
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        retryRef.current = 0;
        setStatus("live");
        ws.send(
          JSON.stringify({
            type: "subscribe",
            cluster_id: clusterId || undefined,
            namespace: namespace || undefined,
            resources,
          })
        );
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "live_event" && msg.resource_type) {
            setLastEventAt(msg.timestamp || new Date().toISOString());
            invalidateForResource(msg.resource_type);
          }
        } catch {
          /* ignore malformed */
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus("reconnecting");
        const delay = Math.min(30000, 1000 * 2 ** retryRef.current);
        retryRef.current += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [clusterId, namespace, resources.join(","), enabled, invalidateForResource]);

  return { status, lastEventAt };
}

export function LiveStatusBadge({ status }: { status: LiveWatchStatus }) {
  const styles: Record<LiveWatchStatus, string> = {
    live: "bg-green-100 text-green-700",
    connecting: "bg-blue-100 text-blue-700",
    reconnecting: "bg-amber-100 text-amber-700",
    offline: "bg-gray-100 text-gray-600",
  };
  const labels: Record<LiveWatchStatus, string> = {
    live: "Live",
    connecting: "Connecting…",
    reconnecting: "Reconnecting…",
    offline: "Offline",
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}
