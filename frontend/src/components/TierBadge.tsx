/**
 * TierBadge — Prod / Non-Prod chip for a subscription, grant or request line.
 *
 * Colours match the environment badges already used on the admin pages
 * (Prod red, Non-Prod blue) so the two read as the same concept.
 */

import React from "react";

export type SubscriptionTier = "prod" | "nonprod";

const TIER_STYLES: Record<SubscriptionTier, string> = {
  prod: "bg-red-100 text-red-700",
  nonprod: "bg-blue-100 text-blue-700",
};

export const TIER_LABELS: Record<SubscriptionTier, string> = {
  prod: "Prod",
  nonprod: "Non-Prod",
};

interface TierBadgeProps {
  tier: SubscriptionTier | null | undefined;
  /** Text shown when the tier is unknown (e.g. a whole-subscription grant). */
  emptyLabel?: string;
  className?: string;
}

const TierBadge: React.FC<TierBadgeProps> = ({ tier, emptyLabel = "—", className = "" }) => {
  if (tier !== "prod" && tier !== "nonprod") {
    return <span className={`text-xs text-gray-400 ${className}`}>{emptyLabel}</span>;
  }
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold whitespace-nowrap ${TIER_STYLES[tier]} ${className}`}
    >
      {TIER_LABELS[tier]}
    </span>
  );
};

export default TierBadge;
