/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AZURE_CLIENT_ID: string;
  readonly VITE_AZURE_TENANT_ID: string;
  readonly VITE_REDIRECT_URI: string;
  readonly VITE_API_BASE_URL: string;
}

interface OpsPortalRuntimeConfig {
  VITE_AZURE_CLIENT_ID?: string;
  VITE_AZURE_TENANT_ID?: string;
  VITE_REDIRECT_URI?: string;
  VITE_API_BASE_URL?: string;
}

interface Window {
  __OPS_PORTAL_CONFIG__?: OpsPortalRuntimeConfig;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
