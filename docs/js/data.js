// Loads precomputed plates from docs/data/showcase/. No back end needed.

const BASE = "data/showcase";
const ASINH10 = Math.asinh(10);

export async function loadIndex() {
  const res = await fetch(`${BASE}/summary.json`);
  const summary = await res.json();
  return Object.entries(summary).map(([id, entry]) => ({ id, name: entry.name }));
}

// --- Frames ---

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
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

export async function loadTarget(id) {
  const meta = await (await fetch(`${BASE}/${id}/meta.json`)).json();
  const size = meta.size;
  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = size;
  const ctx = scratch.getContext("2d", { willReadFrequently: true });
  const tables = {};
  for (const [det, [lo, hi]] of Object.entries(meta.stretch)) tables[det] = fluxTable(lo, hi);

  const images = await Promise.all(meta.frames.map((f) => loadImage(`${BASE}/${id}/${f.file}`)));
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
