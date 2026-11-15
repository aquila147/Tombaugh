// Small scatter plots for the spectrum and the light curve.

const INK = "#1a1815";
const SOFT = "#5c574e";
const RULE = "#cfc8b8";

// points: [{x, y, shape: "circle" | "square", limit: bool}]
export function drawPlot(canvas, points, xLabel, formatX) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  ctx.font = "10px 'IBM Plex Mono', monospace";
  if (!points.length) return;

  const pad = { left: 8, right: 8, top: 16, bottom: 18 };
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(0, ...ys), Math.max(...ys)];
  if (x1 === x0) x1 = x0 + 1;
  if (y1 === y0) y1 = y0 + 1;
  const px = (x) => pad.left + ((x - x0) / (x1 - x0)) * (w - pad.left - pad.right);
  const py = (y) => h - pad.bottom - ((y - y0) / (y1 - y0)) * (h - pad.top - pad.bottom);

  // Zero line and frame
  ctx.strokeStyle = RULE;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, py(0));
  ctx.lineTo(w - pad.right, py(0));
  ctx.stroke();

  ctx.fillStyle = SOFT;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillText(formatX(x0), pad.left, h - 5);
  ctx.textAlign = "right";
  ctx.fillText(formatX(x1), w - pad.right, h - 5);
  ctx.textAlign = "center";
  ctx.fillText(xLabel, w / 2, h - 5);
  ctx.textAlign = "left";
  ctx.fillText(`max ${y1.toPrecision(3)} MJy/sr`, pad.left, 11);

  ctx.strokeStyle = INK;
  ctx.fillStyle = INK;
  for (const p of points) {
    const x = px(p.x);
    const y = py(p.y);
    ctx.beginPath();
    if (p.limit) {
      ctx.moveTo(x, y - 4);
      ctx.lineTo(x + 4, y + 3);
      ctx.lineTo(x - 4, y + 3);
      ctx.closePath();
      ctx.stroke();
    } else if (p.shape === "square") {
      ctx.strokeRect(x - 2.5, y - 2.5, 5, 5);
    } else {
      ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
}
