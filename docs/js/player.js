// Draws one view of the plate: a frame, a difference, or a stack, plus markings.

import { stretchValue } from "./data.js";
import { gaiaAt, positionAt, skyToImage } from "./sky.js";

const PLATE = [243, 239, 230];
const INK = [26, 24, 21];
const NIGHT = [12, 12, 14];
const LIGHT = [240, 236, 226];
const MARK = "#c8102e";

// Difference tones: background, "was here", "is here now"
const DIFF_TONES = {
  plate: { bg: [200, 194, 180], was: [255, 253, 248], now: INK },
  sky: { bg: [70, 70, 72], was: [0, 0, 0], now: LIGHT },
};
const DIFF_FLOOR_SIGMA = 2;
const DIFF_FULL_SIGMA = 8;

const offscreen = document.createElement("canvas");

// --- Pixel values ---

function mix(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function paintValues(rgba, values, view) {
  const [from, to] = view === "plate" ? [PLATE, INK] : [NIGHT, LIGHT];
  for (let p = 0; p < values.length; p++) {
    const c = mix(from, to, values[p]);
    rgba[p * 4] = c[0];
    rgba[p * 4 + 1] = c[1];
    rgba[p * 4 + 2] = c[2];
    rgba[p * 4 + 3] = 255;
  }
}

function paintDifference(rgba, frame, reference, view) {
  const tones = DIFF_TONES[view];
  const noise = Math.hypot(frame.noise, reference.noise);
  for (let p = 0; p < frame.flux.length; p++) {
    const sigma = (frame.flux[p] - reference.flux[p]) / noise;
    const size = Math.abs(sigma);
    const t = Math.min(1, Math.max(0, (size - DIFF_FLOOR_SIGMA) / (DIFF_FULL_SIGMA - DIFF_FLOOR_SIGMA)));
    const c = mix(tones.bg, sigma > 0 ? tones.now : tones.was, t);
    rgba[p * 4] = c[0];
    rgba[p * 4 + 1] = c[1];
    rgba[p * 4 + 2] = c[2];
    rgba[p * 4 + 3] = 255;
  }
}

// Mean of all frames of one detector, shown with that detector's stretch.
export function stackValues(frames, stretch) {
  const n = frames[0].flux.length;
  const values = new Float32Array(n);
  for (const f of frames) for (let p = 0; p < n; p++) values[p] += f.flux[p];
  for (let p = 0; p < n; p++) values[p] = stretchValue(values[p] / frames.length, stretch[0], stretch[1]);
  return values;
}

// --- Drawing ---

// view: {meta, frame, reference, mode, look, stack, showGaia, pick, frames}
export function render(canvas, view) {
  const { meta } = view;
  const size = meta.size;
  offscreen.width = offscreen.height = size;
  const off = offscreen.getContext("2d");
  const image = off.createImageData(size, size);

  if (view.mode === "diff") {
    paintDifference(image.data, view.frame, view.reference, view.look);
  } else if (view.mode === "stack") {
    paintValues(image.data, view.stack, view.look);
  } else {
    const values = new Float32Array(size * size);
    for (let p = 0; p < values.length; p++) values[p] = view.frame.bytes[p] / 255;
    paintValues(image.data, values, view.look);
  }
  off.putImageData(image, 0, 0);

  const ctx = canvas.getContext("2d");
  const side = canvas.width;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(offscreen, 0, 0, side, side);
  drawMarkings(ctx, side, view);
}

function drawMarkings(ctx, side, view) {
  const { meta, frame } = view;
  const scale = side / meta.size;
  const dpr = window.devicePixelRatio || 1;
  const at = (ra, dec) => {
    const [col, row] = skyToImage(meta, ra, dec);
    return [(col + 0.5) * scale, (row + 0.5) * scale];
  };
  const soft = view.look === "plate" ? "rgba(26,24,21,0.55)" : "rgba(240,236,226,0.6)";
  ctx.lineWidth = dpr;
  ctx.font = `${11 * dpr}px 'IBM Plex Mono', monospace`;

  // Gaia stars moved to the frame date: small open squares in ink
  if (view.showGaia) {
    ctx.strokeStyle = soft;
    for (const star of meta.gaia) {
      const [x, y] = at(...gaiaAt(star, frame.mjd));
      ctx.strokeRect(x - 4 * dpr, y - 4 * dpr, 8 * dpr, 8 * dpr);
    }
  }

  // Compass and scale bar
  ctx.strokeStyle = soft;
  ctx.fillStyle = soft;
  const bar = (60 / meta.pixel_arcsec) * scale;
  const bx = side - 14 * dpr - bar;
  const by = side - 16 * dpr;
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(bx + bar, by);
  ctx.stroke();
  ctx.textAlign = "center";
  ctx.fillText("1 arcmin", bx + bar / 2, by - 5 * dpr);
  ctx.textAlign = "left";
  ctx.fillText("N up, E left", 10 * dpr, 16 * dpr);

  // Target: catalogue path, ring at the frame date, measured positions
  ctx.strokeStyle = MARK;
  ctx.fillStyle = MARK;
  if (meta.catalogue.published_rate !== null) {
    const first = view.frames[0].mjd;
    const last = view.frames[view.frames.length - 1].mjd;
    const [x0, y0] = at(...positionAt(meta.catalogue, first));
    const [x1, y1] = at(...positionAt(meta.catalogue, last));
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    ctx.setLineDash([]);

    for (const point of meta.motion.points) {
      if (!point.used) continue;
      const [x, y] = at(point.ra, point.dec);
      ctx.beginPath();
      ctx.moveTo(x - 3 * dpr, y);
      ctx.lineTo(x + 3 * dpr, y);
      ctx.moveTo(x, y - 3 * dpr);
      ctx.lineTo(x, y + 3 * dpr);
      ctx.stroke();
    }
  }
  const [tx, ty] = at(...positionAt(meta.catalogue, frame.mjd));
  const ring = 16 * dpr;
  ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath();
  ctx.arc(tx, ty, ring, 0, 2 * Math.PI);
  ctx.stroke();
  ctx.textAlign = "left";
  ctx.fillText(meta.name, tx + ring + 4 * dpr, ty - ring + 4 * dpr);

  // Picked point: a red corner bracket with a label
  if (view.pick) {
    const x = (view.pick.col + 0.5) * scale;
    const y = (view.pick.row + 0.5) * scale;
    const r = 9 * dpr;
    ctx.strokeRect(x - r, y - r, 2 * r, 2 * r);
    ctx.fillText("picked", x + r + 4 * dpr, y + r);
  }
}
