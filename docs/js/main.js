import { API_URL } from "../config.js";

// --- Back-end status ---

async function checkApi() {
  const el = document.getElementById("api-status");
  try {
    const res = await fetch(`${API_URL}/api/health`);
    const body = await res.json();
    el.textContent = body.status === "ok" ? `ok, version ${body.version}` : "unexpected reply";
  } catch {
    el.textContent = "unreachable. Live lookups are off.";
  }
}

checkApi();
