import { API_URL } from "../config.js";
import { loadEngine, loadIndex, loadTarget } from "./data.js";
import { render, stackValues } from "./player.js";
import { drawPlot } from "./plots.js";
import { formatCoord, imageToSky, project } from "./sky.js";

const $ = (id) => document.getElementById(id);
const canvas = $("plate");
const params = new URLSearchParams(location.search);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEEDS = [1, 2, 4, 8];
const BLINK_MS = 500;
const MODES = ["frames", "diff", "stack"];

const state = {
  targets: [],
  id: null,
  meta: null,
  all: [],
  frames: [],
  detector: null,
  index: 0,
  a: 0,
  b: 1,
  mode: "frames",
  look: "plate",
  playing: false,
  blinking: false,
  speed: 2,
  showGaia: true,
  pick: null,
  stacks: {},
  timer: null,
  side: "after",
  engine: null,
  visits: [],
};

// --- Loading ---

function note(text) {
  $("plate-note").textContent = text;
  $("plate-note").hidden = !text;
}

async function openTarget(id) {
  stop();
  note("Loading plate.");
  try {
    const { meta, frames } = await loadTarget(id);
    Object.assign(state, { id, meta, all: frames, stacks: {}, pick: null, engine: null });
  } catch (err) {
    note("This plate could not be loaded.");
    return;
  }
  const wanted = params.get("det");
  const detectors = Object.keys(state.meta.stretch);
  const wantEngine = state.mode === "engine";
  setDetector(detectors.includes(wanted) ? wanted : detectors[0]);
  drawTargets();
  drawDetectors();
  drawMotion();
  clearPlots();
  const releases = new Set(state.all.flatMap((f) => f.collections));
  state.mixed = releases.size > 1;
  note("");
  if (wantEngine) await showEngine(state.side);
  if (!reducedMotion && state.mode === "frames") play();
  draw();
}

function useFrames(frames) {
  state.frames = frames;
  state.index = 0;
  state.a = 0;
  state.b = frames.length - 1;
}

function setDetector(detector) {
  state.detector = detector;
  if (state.mode === "engine") state.mode = "frames";
  useFrames(state.all.filter((f) => f.detector === detector));
}

// --- Engine before and after ---

// Single exposures from Data Release 1, as significance maps.
async function showEngine(side) {
  if (!state.meta) return;
  stop();
  if (state.engine === null) {
    note("Loading engine maps.");
    try {
      state.engine = (await loadEngine(state.id, state.meta.size)) || false;
    } catch {
      state.engine = false;
    }
    note("");
  }
  if (!state.engine) {
    state.mode = "frames";
    note("No engine run for this plate.");
    setTimeout(() => note(""), 2500);
    draw();
    return;
  }
  state.side = side;
  if (state.mode !== "engine") {
    const index = state.index;
    state.mode = "engine";
    state.detector = state.engine.detector;
    useFrames(state.engine.frames);
    state.index = Math.min(index, state.frames.length - 1);
    drawDetectors();
  }
  draw();
  updateUrl();
}

// --- Drawing ---

function fitCanvas() {
  const wrap = $("plate-wrap");
  const side = Math.max(120, Math.min(wrap.clientWidth, wrap.clientHeight) - 24);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = canvas.style.height = `${side}px`;
  canvas.width = canvas.height = Math.round(side * dpr);
}

function draw() {
  if (!state.meta || !state.frames.length) return;
  const frame = state.frames[state.index];
  if (state.mode === "stack" && !state.stacks[state.detector]) {
    state.stacks[state.detector] = stackValues(state.frames, state.meta.stretch[state.detector]);
  }
  render(canvas, {
    meta: state.meta,
    frames: state.frames,
    frame,
    reference: state.frames[state.a],
    mode: state.mode,
    look: state.look,
    stack: state.stacks[state.detector],
    side: state.side,
    showGaia: state.showGaia,
    pick: state.pick,
  });
  drawFacts(frame);
}

function drawFacts(frame) {
  const n = state.frames.length;
  const release = frame.collections.join(", ").replaceAll("spherex_", "").toUpperCase();
  const what = {
    frames: "frame",
    diff: "difference from frame A",
    stack: `stack of ${n} visits`,
    engine: state.side === "before" ? "before: plain difference, image noise" : "after: residual, per-pixel noise",
  }[state.mode];
  const rows = [
    ["Date", `${frame.date.replace("T", " ")} UTC`],
    ["Wavelength", `${frame.wavelength_um.toFixed(3)} um`],
    ["Detector", frame.detector],
    ["Release", release],
    ["Exposures", String(frame.n_exposures)],
    ["Frame", `${state.index + 1} of ${n}   A ${state.a + 1}   B ${state.b + 1}`],
    ["Showing", what],
  ];
  if (state.mode === "engine") {
    const e = state.engine;
    rows.push(["5 sigma peaks", `this frame ${frame.peaks_before} before, ${frame.peaks_after} after`]);
    rows.push(["Run mean", `${e.mean_peaks_before} before, ${e.mean_peaks_after} after, over ${e.frames_in_run} exposures`]);
  }
  $("facts").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  const line = `${frame.date.replace("T", " ")} UTC   ${frame.wavelength_um.toFixed(3)} um   ${frame.detector}   ${release}`;
  $("frame-line").textContent = state.mode === "stack" ? `Stack of ${n} visits   ${frame.detector}   ${release}` : line;
  canvas.setAttribute(
    "aria-label",
    `${state.meta.name}, ${what}, ${state.look} view. ${line}. Frame ${state.index + 1} of ${n}.`
  );
  $("legend").hidden = state.mode !== "diff" && state.mode !== "engine";
  $("legend-note").textContent = state.mode === "engine" ? "tone grows from 3 to 8 sigma" : "frame minus frame A";
  // Engine maps are built from one release only
  $("release-note").hidden = !state.mixed || state.mode === "engine";
  press("b-before",state.mode === "engine" && state.side === "before");
  press("b-after", state.mode === "engine" && state.side === "after");
  $("b-play").textContent = state.playing ? "Pause" : "Play";
  press("b-play", state.playing);
  press("b-blink", state.blinking);
  press("b-plate", state.look === "plate");
  press("b-sky", state.look === "sky");
  press("b-gaia", state.showGaia);
  for (const mode of MODES) press(`b-${mode}`, state.mode === mode);
  $("b-speed").textContent = `${state.speed} / s`;
  document.body.classList.toggle("sky", state.look === "sky");
}

function press(id, on) {
  $(id).setAttribute("aria-pressed", String(on));
}

function drawTargets() {
  $("targets").innerHTML = "";
  for (const t of state.targets) {
    const button = document.createElement("button");
    button.textContent = t.name;
    button.setAttribute("aria-pressed", String(t.id === state.id));
    button.addEventListener("click", () => {
      params.delete("det");
      openTarget(t.id);
      updateUrl();
    });
    $("targets").append(button);
  }
}

function drawDetectors() {
  $("detectors").innerHTML = "";
  for (const detector of Object.keys(state.meta.stretch)) {
    const button = document.createElement("button");
    button.textContent = detector;
    button.setAttribute("aria-pressed", String(detector === state.detector));
    button.addEventListener("click", () => {
      stop();
      setDetector(detector);
      drawDetectors();
      draw();
      updateUrl();
    });
    $("detectors").append(button);
  }
}

function drawMotion() {
  const { motion, alignment, catalogue } = state.meta;
  const rows = [];
  if (motion.fit) {
    const f = motion.fit;
    rows.push(["Measured", `${f.rate_arcsec_yr.toFixed(2)} +/- ${f.rate_err_arcsec_yr.toFixed(2)} arcsec/yr`]);
    rows.push(["Published", `${catalogue.published_rate.toFixed(2)} arcsec/yr`]);
    rows.push(["From", `${f.n_points} visits over ${f.baseline_yr.toFixed(2)} yr`]);
  } else {
    rows.push(["Measured", "not a moving target"]);
  }
  rows.push(["Gaia check", `${alignment.frames_aligned} of ${alignment.frames} frames`]);
  rows.push(["Star scatter", `${alignment.median_scatter_arcsec.toFixed(2)} arcsec`]);
  rows.push(["Markings", "ring: catalogue position. Dashes: catalogue path. Crosses: measured."]);
  $("motion").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

// --- Playback ---

function stop() {
  clearInterval(state.timer);
  state.timer = null;
  state.playing = false;
  state.blinking = false;
}

function play() {
  stop();
  state.playing = true;
  state.timer = setInterval(() => step(1, true), 1000 / state.speed);
}

function blink() {
  stop();
  state.blinking = true;
  if (state.mode === "stack") state.mode = "frames";
  state.index = state.a;
  state.timer = setInterval(() => {
    state.index = state.index === state.a ? state.b : state.a;
    draw();
  }, BLINK_MS);
}

function step(by, keepPlaying = false) {
  if (!keepPlaying) stop();
  const n = state.frames.length;
  state.index = (state.index + by + n) % n;
  draw();
}

function setMode(mode) {
  if (state.mode === "engine") {
    state.mode = "frames";
    setDetector(state.detector);
    drawDetectors();
  }
  state.mode = state.mode === mode ? "frames" : mode;
  if (state.mode === "stack") stop();
  draw();
  updateUrl();
}

function setLook(look) {
  state.look = look;
  draw();
  updateUrl();
}

// --- Spectrum and light curve ---

const APERTURE_PX = 3;
const RING_PX = [6, 9];

function median(values) {
  const sorted = [...values].sort((x, y) => x - y);
  return sorted.length ? sorted[sorted.length >> 1] : 0;
}

function measure(frame, col, row) {
  const size = state.meta.size;
  let sum = 0;
  let count = 0;
  let clipped = false;
  const ring = [];
  for (let dy = -RING_PX[1]; dy <= RING_PX[1]; dy++) {
    for (let dx = -RING_PX[1]; dx <= RING_PX[1]; dx++) {
      const x = col + dx;
      const y = row + dy;
      if (x < 0 || y < 0 || x >= size || y >= size) continue;
      const r = Math.hypot(dx, dy);
      const p = y * size + x;
      if (r <= APERTURE_PX) {
        sum += frame.flux[p];
        count += 1;
        clipped ||= frame.bytes[p] === 255;
      } else if (r >= RING_PX[0]) {
        ring.push(frame.flux[p]);
      }
    }
  }
  return { value: sum - count * median(ring), clipped };
}

function pickPoint(event) {
  if (!state.meta) return;
  const box = canvas.getBoundingClientRect();
  const size = state.meta.size;
  const col = Math.floor(((event.clientX - box.left) / box.width) * size);
  const row = Math.floor(((event.clientY - box.top) / box.height) * size);
  if (col < 0 || row < 0 || col >= size || row >= size) return;
  state.pick = { col, row };
  const [ra, dec] = imageToSky(state.meta, col, row);
  const detectors = Object.keys(state.meta.stretch);
  const points = state.all.map((f) => {
    const m = measure(f, col, row);
    return {
      wavelength: f.wavelength_um,
      mjd: f.mjd,
      y: m.value,
      limit: m.clipped,
      shape: f.detector === detectors[0] ? "circle" : "square",
    };
  });
  drawPlot($("plot-spec"), points.map((p) => ({ ...p, x: p.wavelength })), "wavelength, um", (x) => x.toFixed(2));
  drawPlot($("plot-time"), points.map((p) => ({ ...p, x: p.mjd })), "date, MJD", (x) => x.toFixed(0));
  $("spec-hint").textContent = `Picked ${formatCoord(ra, dec)}`;
  $("spec-note").hidden = false;
  const summary = `${points.length} visits at ${formatCoord(ra, dec)}`;
  $("plot-spec").setAttribute("aria-label", `Spectrum: brightness against wavelength, ${summary}`);
  $("plot-time").setAttribute("aria-label", `Light curve: brightness against date, ${summary}`);
  draw();
}

function clearPlots() {
  for (const id of ["plot-spec", "plot-time"]) drawPlot($(id), [], "", String);
  $("spec-hint").textContent = "Click a point on the plate.";
  $("spec-note").hidden = true;
}

// --- URL ---

function updateUrl() {
  const next = new URLSearchParams();
  next.set("ra", state.meta.ra.toFixed(4));
  next.set("dec", state.meta.dec.toFixed(4));
  next.set("fov", String(state.meta.fov_deg));
  next.set("det", state.detector);
  next.set("mode", state.mode === "engine" ? state.side : state.mode);
  if (state.look === "sky") next.set("view", "sky");
  if (params.get("embed") === "1") next.set("embed", "1");
  history.replaceState(null, "", `?${next}`);
}

// Pick the precomputed plate that contains the requested position.
async function chooseTarget() {
  const named = params.get("target");
  if (state.targets.some((t) => t.id === named)) return named;
  const ra = parseFloat(params.get("ra"));
  const dec = parseFloat(params.get("dec"));
  if (Number.isFinite(ra) && Number.isFinite(dec)) {
    const summary = await (await fetch("data/showcase/summary.json")).json();
    for (const t of state.targets) {
      const centre = summary[t.id].centre;
      if (!centre) continue;
      const [east, north] = project(ra, dec, centre[0], centre[1]);
      if (Math.max(Math.abs(east), Math.abs(north)) < (centre[2] * 3600) / 2) return t.id;
    }
    return null;
  }
  return state.targets[0].id;
}

// --- Wiring ---

function wire() {
  $("b-prev").addEventListener("click", () => step(-1));
  $("b-next").addEventListener("click", () => step(1));
  $("b-play").addEventListener("click", () => (state.playing ? (stop(), draw()) : (play(), draw())));
  $("b-speed").addEventListener("click", () => {
    state.speed = SPEEDS[(SPEEDS.indexOf(state.speed) + 1) % SPEEDS.length];
    if (state.playing) play();
    draw();
  });
  $("b-blink").addEventListener("click", () => (state.blinking ? (stop(), draw()) : (blink(), draw())));
  $("b-seta").addEventListener("click", () => ((state.a = state.index), draw()));
  $("b-setb").addEventListener("click", () => ((state.b = state.index), draw()));
  for (const mode of MODES) $(`b-${mode}`).addEventListener("click", () => setMode(mode));
  $("b-before").addEventListener("click", () => showEngine("before"));
  $("b-after").addEventListener("click", () => showEngine("after"));
  $("b-plate").addEventListener("click", () => setLook("plate"));
  $("b-sky").addEventListener("click", () => setLook("sky"));
  $("b-gaia").addEventListener("click", () => ((state.showGaia = !state.showGaia), draw()));
  canvas.addEventListener("click", pickPoint);

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target instanceof HTMLButtonElement && event.key === " ") return;
    const key = event.key.toLowerCase();
    const actions = {
      " ": () => $("b-play").click(),
      arrowleft: () => step(-1),
      arrowright: () => step(1),
      b: () => $("b-blink").click(),
      d: () => setMode("diff"),
      s: () => setMode("stack"),
      e: () => showEngine(state.mode === "engine" && state.side === "before" ? "after" : "before"),
      p: () => setLook(state.look === "plate" ? "sky" : "plate"),
      g: () => $("b-gaia").click(),
    };
    if (actions[key]) {
      event.preventDefault();
      actions[key]();
    }
  });

  new ResizeObserver(() => {
    fitCanvas();
    draw();
  }).observe($("plate-wrap"));
}

async function checkApi() {
  const el = $("api-status");
  try {
    const body = await (await fetch(`${API_URL}/api/health`)).json();
    el.textContent = body.status === "ok" ? "on" : "off";
  } catch {
    el.textContent = "off. Precomputed plates still work.";
  }
}

async function start() {
  if (params.get("embed") === "1") document.body.classList.add("embed");
  if (MODES.includes(params.get("mode"))) state.mode = params.get("mode");
  if (["before", "after"].includes(params.get("mode"))) {
    state.mode = "engine";
    state.side = params.get("mode");
  }
  if (params.get("view") === "sky") state.look = "sky";
  fitCanvas();
  wire();
  checkApi();
  try {
    state.targets = await loadIndex();
  } catch {
    note("Precomputed plates are missing.");
    return;
  }
  const id = await chooseTarget();
  drawTargets();
  if (!id) {
    note("No precomputed plate covers this position. Live lookups arrive with the back end.");
    return;
  }
  await openTarget(id);
}

start();
