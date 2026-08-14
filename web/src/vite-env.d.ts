/// <reference types="vite/client" />

// Declared explicitly because the app reads VITE_API_URL; an untyped
// import.meta.env would compile but hide a typo in the variable name.
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
