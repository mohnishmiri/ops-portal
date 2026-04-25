import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initializeMsal } from "./services/apiClient";
import "./index.css";

/**
 * MSAL v3 requires initialize() + handleRedirectPromise() to finish
 * BEFORE React renders.  Otherwise the redirect response from Azure AD
 * is never processed and UnauthenticatedTemplate shows again.
 */
initializeMsal().then(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}).catch((err) => {
  console.error("MSAL initialization failed:", err);
  // Render anyway so the user at least sees the login page
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});
