/// <reference types="vite/client" />

/**
 * Only public configuration belongs here. Every VITE_* value is inlined into
 * the bundle at build time and is readable by anyone who opens the site.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
