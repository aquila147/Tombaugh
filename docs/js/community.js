// Candidates, anonymous votes and the public sky map.
// Reads and writes Supabase from the browser with the publishable key only.
// Everything here fails quietly: the plates never depend on it.

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "../config.js";

const TIMEOUT_MS = 7000;
const VOTES_PER_HOUR = 10;
const PATCH_DEG = 3;
export const supabaseOn = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

async function rest(path, options = {}) {
  if (!supabaseOn) throw new Error("Supabase is not configured");
  const control = new AbortController();
  const timer = setTimeout(() => control.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
      ...options,
      signal: control.signal,
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    if (!res.ok) {
      const error = new Error(`Supabase answered ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return res.status === 204 || res.headers.get("content-length") === "0" ? null : res.json();
  } finally {
    clearTimeout(timer);
  }
}

// --- Candidates ---

// Live rows with vote counts, or the stored copy if Supabase cannot be reached.
export async function loadCandidates() {
  try {
    const rows = await rest("candidates?select=*&order=id");
    const counts = await rest("candidate_votes?select=*");
    const byId = Object.fromEntries(counts.map((c) => [c.candidate_id, c]));
    for (const row of rows) {
      row.real_votes = byId[row.id]?.real_votes || 0;
      row.artifact_votes = byId[row.id]?.artifact_votes || 0;
    }
    return { rows, live: true };
  } catch {
    try {
      const rows = await (await fetch("data/candidates.json", { cache: "no-cache" })).json();
      return { rows, live: false };
    } catch {
      return { rows: [], live: false };
    }
  }
}

// --- Votes ---

// A random id kept in this browser. It is not tied to a person.
function deviceId() {
  try {
    let id = localStorage.getItem("tombaugh-device");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("tombaugh-device", id);
    }
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

function recentVotes() {
  try {
    const hourAgo = Date.now() - 3600000;
    return JSON.parse(localStorage.getItem("tombaugh-votes") || "[]").filter((t) => t > hourAgo);
  } catch {
    return [];
  }
}

// Returns a short message for the visitor.
export async function castVote(candidateId, vote) {
  const recent = recentVotes();
  if (recent.length >= VOTES_PER_HOUR) return "Vote limit reached for this hour on this device.";
  try {
    await rest("votes", {
      method: "POST",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({ candidate_id: candidateId, device_id: deviceId(), vote }),
    });
    try {
      localStorage.setItem("tombaugh-votes", JSON.stringify([...recent, Date.now()]));
    } catch {
      // Storage may be blocked; the vote still counted
    }
    return "Vote recorded. Thank you.";
  } catch (err) {
    if (err.status === 409) return "This device has already voted on this candidate.";
    return "The vote could not be saved right now.";
  }
}

// --- Public sky map ---

// Only a coarse 3 degree patch is ever written, never a location.
export async function logSearch(ra, dec, source) {
  const decC = Math.max(-90, Math.min(90, Math.round(dec / PATCH_DEG) * PATCH_DEG));
  const raC = ((Math.round(ra / PATCH_DEG) * PATCH_DEG) % 360 + 360) % 360;
  try {
    await rest("sky_searches", {
      method: "POST",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({
        field_id: `${raC}_${decC}`,
        ra_center: raC,
        dec_center: decC,
        source,
      }),
    });
    return true;
  } catch {
    return false;
  }
}

export async function loadSearches() {
  try {
    return await rest("sky_searches?select=ra_center,dec_center&limit=5000");
  } catch {
    return null;
  }
}

// All-sky map, RA increasing to the left as on the sky. Patches are ink squares.
export function drawSkyMap(canvas, searches, plates) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const x = (ra) => w - (ra / 360) * w;
  const y = (dec) => h / 2 - (dec / 180) * h;

  ctx.strokeStyle = "#cfc8b8";
  ctx.lineWidth = 1;
  for (let ra = 0; ra <= 360; ra += 60) {
    ctx.beginPath();
    ctx.moveTo(x(ra), 0);
    ctx.lineTo(x(ra), h);
    ctx.stroke();
  }
  for (let dec = -60; dec <= 60; dec += 30) {
    ctx.beginPath();
    ctx.moveTo(0, y(dec));
    ctx.lineTo(w, y(dec));
    ctx.stroke();
  }
  ctx.fillStyle = "#5c574e";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.fillText("RA 360", 3, h - 4);
  ctx.textAlign = "right";
  ctx.fillText("RA 0", w - 3, h - 4);
  ctx.textAlign = "left";
  ctx.fillText("Dec +90", 3, 11);

  // Stored plates: small open circles
  ctx.strokeStyle = "#1a1815";
  for (const plate of plates) {
    ctx.beginPath();
    ctx.arc(x(plate.centre[0]), y(plate.centre[1]), 3, 0, 2 * Math.PI);
    ctx.stroke();
  }
  // Patches searched by visitors: filled squares
  ctx.fillStyle = "#1a1815";
  const seen = new Set();
  for (const s of searches || []) {
    const key = `${s.ra_center}_${s.dec_center}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const side = Math.max(4, (PATCH_DEG / 360) * w);
    ctx.fillRect(x(s.ra_center) - side / 2, y(s.dec_center) - side / 2, side, side);
  }
  return seen.size;
}
