/**
 * App Entry — Root application with MSAL auth, routing, and access control.
 *
 * Access control layers:
 *  1. MSAL gate (prod only) — user must be authenticated via Azure AD.
 *  2. Role check (AuthContext) — user must have at least one portal role.
 *  3. Module/page check (PermissionsContext + ProtectedRoute) — user or their
 *     role must have an explicit permission record for the page they visit.
 *     Admin role bypasses all checks.
 *
 * Adding a new page:
 *  1. Import the page component.
 *  2. Add a <Route> wrapped in <ProtectedRoute module="…" page="…">.
 *  3. Add a nav entry with the matching module/page strings.
 *  4. Register the resource in backend resource_registry.py.
 */

import React, { Component, ErrorInfo, ReactNode, useEffect } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import { MsalProvider, AuthenticatedTemplate, UnauthenticatedTemplate, useMsal } from "@azure/msal-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { msalInstance } from "./services/apiClient";
import { isDevMode, loginRequest } from "./config/authConfig";
import LeadershipDashboard from "./pages/LeadershipDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import PermissionsManagement from "./features/admin/PermissionsManagement";
import KeyVaultPage from "./pages/KeyVaultPage";
import AKSOperationsPage from "./pages/AKSOperationsPage";
import CompliancePage from "./pages/CompliancePage";
import InfraAlertPage from "./pages/InfraAlertPage";
import AmortizedCostDashboard from "./pages/AmortizedCostDashboard";
import { TimezoneProvider } from "./contexts/TimezoneContext";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { PermissionsProvider, usePermissions } from "./contexts/PermissionsContext";
import ProtectedRoute from "./components/ProtectedRoute";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
    },
  },
});

// ── Brand ──────────────────────────────────────────────────────────────────────

const APP_VERSION = "1.0.0";
const BRAND_LOGO_PATH = "/att-globe.svg?v=20260413c";

const BrandMark: React.FC<{ sizeClassName?: string; imageClassName?: string }> = ({
  sizeClassName = "h-10 w-10",
  imageClassName = "h-full w-full",
}) => (
  <div className={`${sizeClassName} flex items-center justify-center shrink-0`}>
    <img src={BRAND_LOGO_PATH} alt="AT&T logo" className={imageClassName} />
  </div>
);

// ── Navigation ────────────────────────────────────────────────────────────────

/**
 * Nav item definition.
 *
 * module/page strings map directly to resource_name values in the backend
 * resource registry.  Leave them undefined for the admin item which uses
 * the role-based isAdmin check instead.
 */
interface NavItem {
  to: string;
  label: string;
  module?: string;
  page?: string;
}

const ALL_NAV_ITEMS: NavItem[] = [
  { to: "/",           label: "Leadership Dashboard", module: "cost_management",  page: "leadership_dashboard" },
  { to: "/env-costs",  label: "Amortized Costs",      module: "cost_management",  page: "amortized_costs" },
  { to: "/keyvault",   label: "Key Vault",             module: "keyvault",         page: "keyvault_main" },
  { to: "/aks",        label: "AKS Operations",        module: "aks_operations",   page: "aks_main" },
  { to: "/compliance", label: "Compliance",            module: "compliance",       page: "compliance_main" },
  { to: "/infra-alerts", label: "Infra Alerts",        module: "infra_alerts",     page: "infra_alerts_main" },
];

const Navigation: React.FC = () => {
  const msal = isDevMode ? null : useMsal();
  const activeAccount = msal?.instance.getActiveAccount() ?? msal?.accounts?.[0];
  const { isAdmin } = useAuth();
  const { canViewModule, canViewPage, isLoading: permsLoading } = usePermissions();

  // Filter nav items to only those the user can view.
  // While permissions are still loading we show all items (they'll be guarded at the route level).
  const visibleNavItems = ALL_NAV_ITEMS.filter((item) => {
    if (isAdmin || permsLoading) return true;
    const modOk  = item.module ? canViewModule(item.module) : true;
    const pageOk = item.page   ? canViewPage(item.page)   : true;
    return modOk && pageOk;
  });

  return (
    <nav className="bg-white shadow-sm border-b border-att-400/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-3">
              <BrandMark sizeClassName="h-10 w-10" imageClassName="h-full w-full" />
              <div className="flex flex-col leading-none">
                <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-att-500">AT&amp;T</span>
                <span className="font-bold text-gray-900">OpsPortal</span>
              </div>
            </div>

            <div className="hidden md:flex items-center gap-1">
              {visibleNavItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `px-3 py-2 rounded-md text-sm font-medium transition ${
                      isActive
                        ? "bg-att-50 text-att-600"
                        : "text-gray-600 hover:text-att-500 hover:bg-att-50"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
              {isAdmin && (
                <NavLink
                  to="/admin"
                  className={({ isActive }) =>
                    `px-3 py-2 rounded-md text-sm font-medium transition ${
                      isActive ? "bg-att-50 text-att-600" : "text-gray-600 hover:text-att-500 hover:bg-att-50"
                    }`
                  }
                >
                  Admin
                </NavLink>
              )}
            </div>
          </div>

          <div className="flex items-center gap-4">
            {isDevMode && (
              <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded-full font-medium">
                DEV MODE
              </span>
            )}
            <span className="text-sm text-gray-600">
              {isDevMode ? "Local Developer" : activeAccount?.name || activeAccount?.username}
            </span>
            {!isDevMode && (
              <button
                onClick={() => msal?.instance.logoutRedirect()}
                className="px-3 py-1.5 text-sm text-white bg-att-400 rounded-md hover:bg-att-500 transition"
              >
                Sign out
              </button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

// ── Login Page ───────────────────────────────────────────────────────────────��─

const LoginPage: React.FC = () => {
  const { instance } = useMsal();
  return (
    <div className="min-h-screen bg-gradient-to-br from-att-50 to-att-100 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-xl p-10 max-w-md w-full text-center">
        <div className="flex justify-center mb-6">
          <BrandMark sizeClassName="h-28 w-28" imageClassName="h-full w-full" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">AT&T OpsPortal</h1>
        <p className="text-gray-600 mb-8">
          Sign in with your organization account to access infrastructure dashboards, cost analytics, and operational insights.
        </p>
        <button
          onClick={() => instance.loginRedirect(loginRequest)}
          className="w-full px-6 py-3 bg-att-400 text-white font-semibold rounded-lg hover:bg-att-500 transition"
        >
          Sign in with Microsoft
        </button>
      </div>
    </div>
  );
};

// ── Error Boundary ───────────────────────────────────────────────────────────��─

interface ErrorBoundaryState { hasError: boolean; error: Error | null; }

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="bg-white rounded-lg shadow p-8 max-w-lg w-full text-center">
            <h2 className="text-xl font-bold text-red-600 mb-2">Something went wrong</h2>
            <p className="text-gray-600 mb-4">{this.state.error?.message}</p>
            <button
              onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload(); }}
              className="px-4 py-2 bg-att-400 text-white rounded-md hover:bg-att-500"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Footer ─────────────────────────────────────────────────────────────────────

const Footer: React.FC = () => (
  <footer className="bg-att-700 text-white mt-auto">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      <div className="flex flex-col sm:flex-row items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BrandMark sizeClassName="h-9 w-9" imageClassName="h-full w-full" />
          <span className="text-sm font-semibold">AT&T Enterprise OpsPortal</span>
        </div>
        <p className="text-att-200 text-xs">
          &copy; {new Date().getFullYear()} AT&T Intellectual Property. All rights reserved.
        </p>
        <span className="text-xs bg-att-800 text-att-200 px-2 py-0.5 rounded">
          v{APP_VERSION}
        </span>
      </div>
    </div>
  </footer>
);

// ── Admin route guards ─────────────────────────────────────────────────���───────

const AdminRoute: React.FC = () => {
  const { isAdmin } = useAuth();
  return isAdmin ? <AdminDashboard /> : <Navigate to="/" replace />;
};

const AdminPermissionsRoute: React.FC = () => {
  const { isAdmin } = useAuth();
  return isAdmin ? <PermissionsManagement /> : <Navigate to="/" replace />;
};

// ── Main app content ───────────────────────────────────────────────────────────

const MainContent: React.FC = () => (
  <BrowserRouter>
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navigation />
      <main className="flex-1 mx-auto max-w-7xl w-full px-4 sm:px-6 lg:px-8 py-2">
        <Routes>
          {/* Leadership Dashboard — cost_management module */}
          <Route
            path="/"
            element={
              <ProtectedRoute module="cost_management" page="leadership_dashboard" label="Leadership Dashboard">
                <LeadershipDashboard />
              </ProtectedRoute>
            }
          />

          {/* Amortized Costs — cost_management module */}
          <Route
            path="/env-costs"
            element={
              <ProtectedRoute module="cost_management" page="amortized_costs" label="Amortized Costs">
                <AmortizedCostDashboard />
              </ProtectedRoute>
            }
          />

          {/* Key Vault */}
          <Route
            path="/keyvault"
            element={
              <ProtectedRoute module="keyvault" page="keyvault_main" label="Key Vault">
                <KeyVaultPage />
              </ProtectedRoute>
            }
          />

          {/* AKS Operations */}
          <Route
            path="/aks"
            element={
              <ProtectedRoute module="aks_operations" page="aks_main" label="AKS Operations">
                <AKSOperationsPage />
              </ProtectedRoute>
            }
          />

          {/* Compliance */}
          <Route
            path="/compliance"
            element={
              <ProtectedRoute module="compliance" page="compliance_main" label="Compliance">
                <CompliancePage />
              </ProtectedRoute>
            }
          />

          {/* Infra Alerts */}
          <Route
            path="/infra-alerts"
            element={
              <ProtectedRoute module="infra_alerts" page="infra_alerts_main" label="Infrastructure Alerts">
                <InfraAlertPage />
              </ProtectedRoute>
            }
          />

          {/* Admin — role-gated (admin role only, no resource record needed) */}
          <Route path="/admin" element={<AdminRoute />} />
          <Route path="/admin/permissions" element={<AdminPermissionsRoute />} />

          {/* Legacy redirect */}
          <Route path="/optimization" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  </BrowserRouter>
);

// ── Root ───────────────────────────────────────────────────────────────────────

const App: React.FC = () => {
  useEffect(() => {
    const iconLinks: Array<{ rel: string; type?: string }> = [
      { rel: "icon", type: "image/svg+xml" },
      { rel: "shortcut icon" },
      { rel: "apple-touch-icon" },
    ];
    iconLinks.forEach(({ rel, type }) => {
      let link = document.head.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement | null;
      if (!link) { link = document.createElement("link"); link.rel = rel; document.head.appendChild(link); }
      if (type) link.type = type;
      link.href = BRAND_LOGO_PATH;
    });
  }, []);

  if (isDevMode) {
    console.info(
      "%c[DEV MODE]%c Azure AD credentials not configured — auth bypassed.",
      "background:#f59e0b;color:#000;padding:2px 6px;border-radius:3px;font-weight:bold",
      ""
    );
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <PermissionsProvider>
            <TimezoneProvider>
              <ErrorBoundary>
                <MainContent />
              </ErrorBoundary>
            </TimezoneProvider>
          </PermissionsProvider>
        </AuthProvider>
      </QueryClientProvider>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      <QueryClientProvider client={queryClient}>
        <UnauthenticatedTemplate>
          <LoginPage />
        </UnauthenticatedTemplate>

        <AuthenticatedTemplate>
          <AuthProvider>
            <PermissionsProvider>
              <TimezoneProvider>
                <ErrorBoundary>
                  <MainContent />
                </ErrorBoundary>
              </TimezoneProvider>
            </PermissionsProvider>
          </AuthProvider>
        </AuthenticatedTemplate>
      </QueryClientProvider>
    </MsalProvider>
  );
};

export default App;
