// Loads precomputed plates from docs/data/showcase/. No back end needed.

const BASE = "data/showcase";
const ASINH10 = Math.asinh(10);

export async function loadIndex() {
  const res = await fetch(`${BASE}/summary.json`, { cache: "no-cache" });
  const summary = await res.json();
  return Object.entries(summary).map(([id, entry]) => ({
    id,
    name: entry.title || entry.name,
    centre: entry.centre,
    demo: Boolean(entry.demo),
  }));
}

// --- Frames ---

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    // Live plates come from the back end, a different origin
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Could not load ${url}`));
    img.src = url;
  });
}

// PNG bytes hold an asinh stretch between lo and hi. Undo it to get brightness back.
function fluxTable(lo, hi) {
  const table = new Float32Array(256);
  for (let v = 0; v < 256; v++) {
    table[v] = lo + (Math.sinh((v / 255) * ASINH10) / 10) * (hi - lo);
  }
  return table;
}

export function stretchValue(flux, lo, hi) {
  const scaled = Math.min(1, Math.max(0, (flux - lo) / (hi - lo)));
  return Math.asinh(10 * scaled) / ASINH10;
}

// Before and after significance maps from the engine, or null if this plate has none.
export async function loadEngine(id, size, base = BASE) {
  const res = await fetch(`${base}/${id}/engine/engine.json`, { cache: "no-cache" });
  if (!res.ok) return null;
  const meta = await res.json();
  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = size;
  const ctx = scratch.getContext("2d", { willReadFrequently: true });
  const files = meta.frames.flatMap((f) => [f.before, f.after]);
  const loaded = await Promise.all(files.map((f) => loadImage(`${base}/${id}/engine/${f}`)));
  const images = Object.fromEntries(files.map((f, i) => [f, loaded[i]]));
  const read = (file) => {
    ctx.drawImage(images[file], 0, 0);
    const rgba = ctx.getImageData(0, 0, size, size).data;
    const sigma = new Float32Array(size * size);
    for (let p = 0; p < sigma.length; p++) {
      sigma[p] = ((rgba[p * 4] / 255) * 2 - 1) * meta.sigma_range;
    }
    return sigma;
  };
  const frames = [];
  for (const f of meta.frames) {
    frames.push({ ...f, before: read(f.before), after: read(f.after) });
  }
  return { ...meta, frames };
}

export async function loadTarget(id, base = BASE) {
  const meta = await (await fetch(`${base}/${id}/meta.json`, { cache: "no-cache" })).json();
  const size = meta.size;
  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = size;
  const ctx = scratch.getContext("2d", { willReadFrequently: true });
  const tables = {};
  for (const [det, [lo, hi]] of Object.entries(meta.stretch)) tables[det] = fluxTable(lo, hi);

  const images = await Promise.all(meta.frames.map((f) => loadImage(`${base}/${id}/${f.file}`)));
  const frames = meta.frames.map((f, i) => {
    ctx.drawImage(images[i], 0, 0);
    const rgba = ctx.getImageData(0, 0, size, size).data;
    const bytes = new Uint8Array(size * size);
    const flux = new Float32Array(size * size);
    const table = tables[f.detector];
    for (let p = 0; p < bytes.length; p++) {
      bytes[p] = rgba[p * 4];
      flux[p] = table[bytes[p]];
    }
    return { ...f, bytes, flux };
  });
  return { meta, frames };
}
