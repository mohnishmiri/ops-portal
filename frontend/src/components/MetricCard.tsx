import React from "react";

type MetricCardTone =
  | "att"
  | "blue"
  | "green"
  | "emerald"
  | "amber"
  | "orange"
  | "red"
  | "purple"
  | "indigo"
  | "slate";

const toneStyles: Record<
  MetricCardTone,
  {
    accent: string;
    iconSurface: string;
    value: string;
  }
> = {
  att: {
    accent: "from-att-300 via-att-500 to-att-300",
    iconSurface: "bg-att-100 text-att-700",
    value: "text-slate-900",
  },
  blue: {
    accent: "from-blue-200 via-blue-500 to-blue-200",
    iconSurface: "bg-blue-100 text-blue-700",
    value: "text-blue-900",
  },
  green: {
    accent: "from-green-200 via-green-500 to-green-200",
    iconSurface: "bg-green-100 text-green-700",
    value: "text-green-900",
  },
  emerald: {
    accent: "from-emerald-200 via-emerald-500 to-emerald-200",
    iconSurface: "bg-emerald-100 text-emerald-700",
    value: "text-emerald-900",
  },
  amber: {
    accent: "from-amber-200 via-amber-500 to-amber-200",
    iconSurface: "bg-amber-100 text-amber-700",
    value: "text-amber-900",
  },
  orange: {
    accent: "from-orange-200 via-orange-500 to-orange-200",
    iconSurface: "bg-orange-100 text-orange-700",
    value: "text-orange-900",
  },
  red: {
    accent: "from-red-200 via-red-500 to-red-200",
    iconSurface: "bg-red-100 text-red-700",
    value: "text-red-900",
  },
  purple: {
    accent: "from-purple-200 via-purple-500 to-purple-200",
    iconSurface: "bg-purple-100 text-purple-700",
    value: "text-purple-900",
  },
  indigo: {
    accent: "from-indigo-200 via-indigo-500 to-indigo-200",
    iconSurface: "bg-indigo-100 text-indigo-700",
    value: "text-indigo-900",
  },
  slate: {
    accent: "from-slate-200 via-slate-500 to-slate-200",
    iconSurface: "bg-slate-100 text-slate-700",
    value: "text-slate-900",
  },
};

export interface MetricCardProps {
  title: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  subtitle?: React.ReactNode;
  meta?: React.ReactNode;
  tone?: MetricCardTone;
  className?: string;
  valueClassName?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  icon,
  subtitle,
  meta,
  tone = "att",
  className = "",
  valueClassName = "",
}) => {
  const styles = toneStyles[tone];

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-5 shadow-sm shadow-att-100/40 ${className}`}
    >
      <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${styles.accent}`} />
      <div className="flex items-start gap-3">
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ring-1 ring-white/60 ${styles.iconSurface}`}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            {title}
          </p>
          <div className="mt-1 flex flex-wrap items-end gap-x-3 gap-y-1">
            <p className={`text-2xl font-bold ${styles.value} ${valueClassName}`}>{value}</p>
            {meta}
          </div>
          {subtitle ? <p className="mt-1 text-xs text-slate-400">{subtitle}</p> : null}
        </div>
      </div>
    </div>
  );
};

const iconProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 24 24",
};

export const MetricCardIcons = {
  currency: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M12 2v20" />
      <path d="M17 6.5c0-1.93-2.24-3.5-5-3.5s-5 1.57-5 3.5S9.24 10 12 10s5 1.57 5 3.5S14.76 17 12 17s-5-1.57-5-3.5" />
    </svg>
  ),
  layers: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="m12 3 9 4.5-9 4.5-9-4.5L12 3Z" />
      <path d="m3 12 9 4.5 9-4.5" />
      <path d="m3 16.5 9 4.5 9-4.5" />
    </svg>
  ),
  server: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <rect x="3" y="4" width="18" height="6" rx="2" />
      <rect x="3" y="14" width="18" height="6" rx="2" />
      <path d="M7 7h.01" />
      <path d="M7 17h.01" />
      <path d="M11 7h6" />
      <path d="M11 17h6" />
    </svg>
  ),
  database: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <ellipse cx="12" cy="5" rx="7" ry="3" />
      <path d="M5 5v6c0 1.66 3.13 3 7 3s7-1.34 7-3V5" />
      <path d="M5 11v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" />
    </svg>
  ),
  shield: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
  alert: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  ),
  calendar: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4" />
      <path d="M8 2v4" />
      <path d="M3 10h18" />
    </svg>
  ),
  globe: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14.5 14.5 0 0 1 0 18" />
      <path d="M12 3a14.5 14.5 0 0 0 0 18" />
    </svg>
  ),
  activity: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M22 12h-4l-3 7-6-14-3 7H2" />
    </svg>
  ),
  checkCircle: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
  cloud: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M18 18H7a4 4 0 1 1 .53-7.96A5.5 5.5 0 1 1 18 18Z" />
    </svg>
  ),
  chart: (cls = "h-5 w-5") => (
    <svg className={cls} {...iconProps}>
      <path d="M3 3v18h18" />
      <path d="m7 14 4-4 3 3 5-7" />
    </svg>
  ),
};
