/**
 * Optimization Recommendations Page — detailed FinOps recommendations.
 */

import React, { useState } from "react";
import {
  useRecommendations,
  useOptimizationSummary,
  CostRecommendation,
} from "../services/costApi";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { useAuth } from "../contexts/AuthContext";

// ── Confidence Badge ──────────────────────────────────────────────────

const ConfidenceBadge: React.FC<{ level: string; score: number }> = ({
  level,
  score,
}) => {
  const colorMap: Record<string, string> = {
    high: "bg-green-100 text-green-800",
    medium: "bg-yellow-100 text-yellow-800",
    low: "bg-red-100 text-red-800",
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
        colorMap[level] || colorMap.medium
      }`}
    >
      {level.toUpperCase()} ({score.toFixed(0)}%)
    </span>
  );
};

// ── Priority Badge ────────────────────────────────────────────────────

const PriorityBadge: React.FC<{ priority: string }> = ({ priority }) => {
  const colorMap: Record<string, string> = {
    critical: "bg-red-600 text-white",
    high: "bg-red-100 text-red-800",
    medium: "bg-orange-100 text-orange-800",
    low: "bg-blue-100 text-blue-800",
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
        colorMap[priority] || colorMap.medium
      }`}
    >
      {priority.toUpperCase()}
    </span>
  );
};

// ── Recommendation Card ───────────────────────────────────────────────

const RecommendationCard: React.FC<{ rec: CostRecommendation }> = ({
  rec,
}) => {
  const { canWrite } = useAuth();
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <PriorityBadge priority={rec.priority} />
            <ConfidenceBadge level={rec.confidence} score={rec.confidence_score} />
            <span className="text-xs text-gray-400 ml-auto">
              {rec.source === "azure_advisor" ? "Azure Advisor" : "Custom Analysis"}
            </span>
          </div>
          <h4 className="text-base font-semibold text-gray-900">{rec.title}</h4>
          <p className="text-sm text-gray-600 mt-1">{rec.description}</p>
        </div>
        <div className="text-right ml-6 min-w-[140px]">
          <p className="text-xl font-bold text-green-600">
            ${rec.estimated_annual_savings.toLocaleString()}
          </p>
          <p className="text-xs text-gray-500">annual savings</p>
          <p className="text-sm text-gray-600 mt-1">
            ${rec.estimated_monthly_savings.toLocaleString()}/mo
          </p>
        </div>
      </div>

      {/* Expandable details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-sm text-blue-600 hover:text-blue-800 mt-3"
      >
        {expanded ? "Hide details ▲" : "Show details ▼"}
      </button>

      {expanded && (
        <div className="mt-4 pt-4 border-t border-gray-100 grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="font-medium text-gray-700">Resource</p>
            <p className="text-gray-600">{rec.resource.resource_name}</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Type</p>
            <p className="text-gray-600">{rec.resource.resource_type}</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Resource Group</p>
            <p className="text-gray-600">{rec.resource.resource_group}</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Location</p>
            <p className="text-gray-600">{rec.resource.location}</p>
          </div>
          <div className="col-span-2">
            <p className="font-medium text-gray-700">Recommended Action</p>
            <p className="text-gray-600">{rec.action_required}</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Risk Level</p>
            <p className="text-gray-600 capitalize">{rec.risk_level}</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Current Monthly Cost</p>
            <p className="text-gray-600">
              ${rec.current_monthly_cost.toLocaleString()}
            </p>
          </div>
          <div className="col-span-2 flex gap-3 mt-2">
            {canWrite && (
            <>
            <button className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700">
              Mark Implemented
            </button>
            <button className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded-lg hover:bg-gray-300">
              Dismiss
            </button>
            </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────

const OptimizationPage: React.FC = () => {
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const { data: recommendations, isLoading } = useRecommendations(
    categoryFilter || undefined
  );
  const { data: summary } = useOptimizationSummary();

  const categories = [
    { value: "", label: "All Categories" },
    { value: "idle_resources", label: "Idle Resources" },
    { value: "underutilized_vms", label: "Underutilized VMs" },
    { value: "unattached_disks", label: "Unattached Disks" },
    { value: "orphaned_snapshots", label: "Orphaned Snapshots" },
    { value: "overprovisioned_skus", label: "Overprovisioned SKUs" },
    { value: "reserved_instances", label: "Reserved Instances" },
    { value: "savings_plans", label: "Savings Plans" },
    { value: "right_sizing", label: "Right-Sizing" },
  ];

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Cost Optimization Recommendations
          </h1>
          <p className="text-sm text-gray-500">
            {summary?.total_recommendations || 0} recommendations •{" "}
            ${summary?.total_estimated_annual_savings.toLocaleString() || "0"}{" "}
            annual savings potential
          </p>
        </div>

        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg text-sm bg-white"
        >
          {categories.map((cat) => (
            <option key={cat.value} value={cat.value}>
              {cat.label}
            </option>
          ))}
        </select>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Monthly Savings"
            value={`$${summary.total_estimated_monthly_savings.toLocaleString()}`}
            icon={MetricCardIcons.currency()}
            tone="green"
          />
          <MetricCard
            title="Total Recommendations"
            value={summary.total_recommendations}
            icon={MetricCardIcons.layers()}
            tone="blue"
          />
          <MetricCard
            title="Idle VMs"
            value={summary.wastage.idle_vms_count}
            icon={MetricCardIcons.server()}
            tone="orange"
          />
          <MetricCard
            title="Unattached Disks"
            value={summary.wastage.unattached_disks_count}
            icon={MetricCardIcons.database()}
            tone="red"
          />
        </div>
      )}

      {/* Recommendations List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
        </div>
      ) : (
        <div className="space-y-4">
          {recommendations?.map((rec) => (
            <RecommendationCard key={rec.id} rec={rec} />
          ))}
        </div>
      )}
    </div>
  );
};

export default OptimizationPage;
