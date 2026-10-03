/**
 * Per-user subscription scope — persisted server-side per user_id.
 * Does not affect other logged-in users.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import apiClient, { setSubscriptionScopeParam } from "../services/apiClient";
import { useAuth } from "./AuthContext";
import { useSession } from "./SessionContext";

/**
 * A subscription the user may pick. The backend lists only subscriptions the
 * user was granted; project / app / tier are null when the subscription has
 * not been placed in an app yet (visible to Super Admins only).
 */
export interface AvailableSubscription {
  subscription_id: string;
  subscription_name: string;
  environment?: string | null;
  state?: string;
  selected?: boolean;
  tier?: "prod" | "nonprod" | null;
  app_id?: number | null;
  app_name?: string | null;
  app_code?: string | null;
  project_id?: number | null;
  project_name?: string | null;
}

interface SubscriptionContextValue {
  availableSubscriptions: AvailableSubscription[];
  selectedSubscriptionIds: string[];
  effectiveSubscriptionIds: string[];
  isLoading: boolean;
  isAllSelected: boolean;
  scopeLabel: string;
  setSelectedSubscriptionIds: (ids: string[]) => Promise<void>;
  selectAllSubscriptions: () => Promise<void>;
  refreshScope: () => Promise<void>;
}

const SubscriptionContext = createContext<SubscriptionContextValue | undefined>(undefined);

export const SubscriptionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { userId } = useAuth();
  const { session } = useSession();
  const queryClient = useQueryClient();
  // Changes when an approval or revocation changes what the user may see, so
  // the picker reloads its list instead of offering stale subscriptions.
  const accessKey = [
    session?.access?.has_subscription_access ?? "",
    session?.access?.readable_count ?? "",
    session?.access?.writable_count ?? "",
  ].join(":");
  const [availableSubscriptions, setAvailableSubscriptions] = useState<AvailableSubscription[]>([]);
  const [selectedSubscriptionIds, setSelectedSubscriptionIdsState] = useState<string[]>([]);
  const [effectiveSubscriptionIds, setEffectiveSubscriptionIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const applyScope = useCallback((selected: string[], effective: string[]) => {
    setSelectedSubscriptionIdsState(selected);
    setEffectiveSubscriptionIds(effective);
    setSubscriptionScopeParam(selected.length > 0 ? selected : null);
  }, []);

  const refreshScope = useCallback(async () => {
    if (!userId) {
      applyScope([], []);
      setAvailableSubscriptions([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/auth/available-subscriptions");
      setAvailableSubscriptions(data.subscriptions || []);
      applyScope(data.selected_subscription_ids || [], data.effective_subscription_ids || []);
    } finally {
      setIsLoading(false);
    }
  }, [applyScope, userId]);

  useEffect(() => {
    refreshScope();
  }, [refreshScope, accessKey]);

  const persistSelection = useCallback(
    async (ids: string[]) => {
      const { data } = await apiClient.put("/auth/subscription-scope", {
        selected_subscription_ids: ids,
      });
      applyScope(data.selected_subscription_ids || [], data.effective_subscription_ids || []);
      await queryClient.invalidateQueries();
    },
    [applyScope, queryClient],
  );

  const setSelectedSubscriptionIds = useCallback(
    async (ids: string[]) => {
      await persistSelection(ids);
    },
    [persistSelection],
  );

  const selectAllSubscriptions = useCallback(async () => {
    await persistSelection([]);
  }, [persistSelection]);

  const isAllSelected = selectedSubscriptionIds.length === 0;

  const scopeLabel = useMemo(() => {
    if (isAllSelected) {
      const count = effectiveSubscriptionIds.length || availableSubscriptions.length;
      // "All" is everything this user may see (their grants), not every
      // monitored subscription — only a Super Admin sees all of those.
      return count > 0 ? `All available (${count})` : "No subscriptions";
    }
    if (selectedSubscriptionIds.length === 1) {
      const match = availableSubscriptions.find(
        (sub) => sub.subscription_id === selectedSubscriptionIds[0],
      );
      return match?.subscription_name || selectedSubscriptionIds[0];
    }
    return `${selectedSubscriptionIds.length} subscriptions`;
  }, [
    availableSubscriptions,
    effectiveSubscriptionIds.length,
    isAllSelected,
    selectedSubscriptionIds,
  ]);

  const value = useMemo(
    () => ({
      availableSubscriptions,
      selectedSubscriptionIds,
      effectiveSubscriptionIds,
      isLoading,
      isAllSelected,
      scopeLabel,
      setSelectedSubscriptionIds,
      selectAllSubscriptions,
      refreshScope,
    }),
    [
      availableSubscriptions,
      effectiveSubscriptionIds,
      isAllSelected,
      isLoading,
      refreshScope,
      scopeLabel,
      selectAllSubscriptions,
      selectedSubscriptionIds,
      setSelectedSubscriptionIds,
    ],
  );

  return <SubscriptionContext.Provider value={value}>{children}</SubscriptionContext.Provider>;
};

export function useSubscriptionScope(): SubscriptionContextValue {
  const ctx = useContext(SubscriptionContext);
  if (!ctx) {
    throw new Error("useSubscriptionScope must be used within SubscriptionProvider");
  }
  return ctx;
}
