/**
 * App Entry — Root application with MSAL auth and routing.
 *
 * When running in dev mode (no Azure AD credentials) the MSAL auth gate is
 * bypassed and the dashboard renders immediately.
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

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
});

// ── Navigation ────────────────────────────────────────────────────────

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

const Navigation: React.FC = () => {
  // useMsal() is only valid inside <MsalProvider>, so guard for dev mode
  const msal = isDevMode ? null : useMsal();
  const activeAccount = msal?.instance.getActiveAccount() ?? msal?.accounts?.[0];
  const { isAdmin } = useAuth();

  const navItems = [
    { to: "/", label: "Leadership Dashboard" },
    { to: "/env-costs", label: "Amortized Costs" },
    { to: "/keyvault", label: "Key Vault" },
    { to: "/aks", label: "AKS Operations" },
    { to: "/compliance", label: "Compliance" },
    { to: "/infra-alerts", label: "Infra Alerts" },
    ...(isAdmin ? [{ to: "/admin", label: "Admin" }] : []),
  ];

  return (
    <nav className="bg-white shadow-sm border-b border-att-400/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-3">
              <BrandMark sizeClassName="h-10 w-10" imageClassName="h-full w-full" />
              <div className="flex flex-col leading-none">
                <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-att-500">
                  AT&amp;T
                </span>
                <span className="font-bold text-gray-900">OpsPortal</span>
              </div>
            </div>

            <div className="hidden md:flex items-center gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
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
            </div>
          </div>

          <div className="flex items-center gap-4">
            {isDevMode && (
              <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded-full font-medium">
                DEV MODE
              </span>
            )}
            <span className="text-sm text-gray-600">
              {isDevMode
                ? "Local Developer"
                : activeAccount?.name || activeAccount?.username}
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

// ── Login Page ────────────────────────────────────────────────────────

const LoginPage: React.FC = () => {
  const { instance } = useMsal();

  return (
    <div className="min-h-screen bg-gradient-to-br from-att-50 to-att-100 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-xl p-10 max-w-md w-full text-center">
        <div className="flex justify-center mb-6">
          <BrandMark sizeClassName="h-28 w-28" imageClassName="h-full w-full" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          AT&T OpsPortal
        </h1>
        <p className="text-gray-600 mb-8">
          Sign in with your organization account to access infrastructure
          dashboards, cost analytics, and operational insights.
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

// ── Root App ──────────────────────────────────────────────────────────

// ── Error Boundary ────────────────────────────────────────────────────

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

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

// ── Main content (shared between dev and prod modes) ─────────────────

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

/** Route guard — redirects non-admin users away from /admin. */
const AdminRoute: React.FC = () => {
  const { isAdmin } = useAuth();
  return isAdmin ? <AdminDashboard /> : <Navigate to="/" replace />;
};

const AdminPermissionsRoute: React.FC = () => {
  const { isAdmin } = useAuth();
  return isAdmin ? <PermissionsManagement /> : <Navigate to="/" replace />;
};

const MainContent: React.FC = () => (
  <BrowserRouter>
    <div className="min-h-screen flex flex-col bg-gray-50">
      <Navigation />
      <main className="flex-1 mx-auto max-w-7xl w-full px-4 sm:px-6 lg:px-8 py-2">
        <Routes>
          <Route path="/" element={<LeadershipDashboard />} />
          <Route path="/optimization" element={<Navigate to="/" replace />} />
          <Route path="/env-costs" element={<AmortizedCostDashboard />} />
          <Route path="/keyvault" element={<KeyVaultPage />} />
          <Route path="/aks" element={<AKSOperationsPage />} />
          <Route path="/compliance" element={<CompliancePage />} />
          <Route path="/infra-alerts" element={<InfraAlertPage />} />
          <Route path="/admin" element={<AdminRoute />} />
          <Route path="/admin/permissions" element={<AdminPermissionsRoute />} />
        </Routes>
      </main>
      <Footer />
    </div>
  </BrowserRouter>
);

const App: React.FC = () => {
  useEffect(() => {
    const iconLinks: Array<{ rel: string; type?: string }> = [
      { rel: "icon", type: "image/svg+xml" },
      { rel: "shortcut icon" },
      { rel: "apple-touch-icon" },
    ];

    iconLinks.forEach(({ rel, type }) => {
      let link = document.head.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement | null;

      if (!link) {
        link = document.createElement("link");
        link.rel = rel;
        document.head.appendChild(link);
      }

      if (type) {
        link.type = type;
      }

      link.href = BRAND_LOGO_PATH;
    });
  }, []);

  // In dev mode, skip MSAL entirely and render the app directly
  if (isDevMode) {
    console.info(
      "%c[DEV MODE]%c Azure AD credentials not configured — auth bypassed.",
      "background:#f59e0b;color:#000;padding:2px 6px;border-radius:3px;font-weight:bold",
      ""
    );
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TimezoneProvider>
            <ErrorBoundary>
              <MainContent />
            </ErrorBoundary>
          </TimezoneProvider>
        </AuthProvider>
      </QueryClientProvider>
    );
  }

  // Production: full MSAL auth gate
  return (
    <MsalProvider instance={msalInstance}>
      <QueryClientProvider client={queryClient}>
        <UnauthenticatedTemplate>
          <LoginPage />
        </UnauthenticatedTemplate>

        <AuthenticatedTemplate>
          <AuthProvider>
            <TimezoneProvider>
              <ErrorBoundary>
                <MainContent />
              </ErrorBoundary>
            </TimezoneProvider>
          </AuthProvider>
        </AuthenticatedTemplate>
      </QueryClientProvider>
    </MsalProvider>
  );
};

export default App;
