// Back-end address. Put the deployed URL here (Azure Container Apps, or the
// Hugging Face fallback). Leave it empty and the site still works from the
// stored plates, with live lookups switched off.
const PRODUCTION_API_URL = "";

// On a developer's machine the local back end is used instead.
const local = ["localhost", "127.0.0.1"].includes(location.hostname);
export const API_URL = local ? "http://localhost:8000" : PRODUCTION_API_URL;

// Public values only: the project URL and the publishable key.
// Row level security lets this key read, and add votes and sky searches only.
// The service key never goes here.
export const SUPABASE_URL = "https://gkiwtyzwdejrhgfgixxa.supabase.co";
export const SUPABASE_ANON_KEY = "sb_publishable__tUi9UAJbUVjeMUgrdd9wg_mZkro9-Y";
