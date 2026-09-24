/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Live backend API base URL, e.g. "https://oiltrace-api.onrender.com". */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}