import { API_URL } from "../config.js";
import { castVote, drawSkyMap, loadCandidates, loadSearches, logSearch } from "./community.js";
import { loadEngine, loadIndex, loadTarget } from "./data.js";
import { render, stackValues } from "./player.js";
import { drawPlot } from "./plots.js";
import { fieldCentre, parsePlace, zenith } from "./overhead.js";
import { formatCoord, imageToSky, positionAt, project, skyToImage } from "./sky.js";

const $ = (id) => document.getElementById(id);
const canvas = $("plate");
const params = new URLSearchParams(location.search);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEEDS = [1, 2, 4, 8];
// Slower blink and playback for visitors who ask for reduced motion
const BLINK_MS = reducedMotion ? 1200 : 500;
const LIVE_FOV_DEG = 0.2;
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
  speed: reducedMotion ? 1 : 2,
  showGaia: true,
  pick: null,
  stacks: {},
  timer: null,
  side: "after",
  base: undefined,
  apiOn: false,
  candidates: [],
  candidatesLive: false,
  selected: null,
  engine: null,
  visits: [],
};

// --- Loading ---

function note(text) {
  $("plate-note").textContent = text;
  $("plate-note").hidden = !text;
}

async function openTarget(id, base) {
  stop();
  note("Loading plate.");
  try {
    const { meta, frames } = await loadTarget(id, base);
    Object.assign(state, {
      base, id, meta, all: frames, stacks: {}, pick: null, engine: null });
  } catch (err) {
    note("This plate could not be loaded.");
    return;
  }
  const wanted = params.get("det");
  const detectors = Object.keys(state.meta.stretch);
  const wantEngine = state.mode === "engine";
  // A fast mover is seen by different detectors on different visits, so show them all
  const first = state.meta.kind === "asteroid" ? "all" : detectors[0];
  setDetector(detectors.includes(wanted) || wanted === "all" ? wanted : first);
  drawTargets();
  drawDetectors();
  drawMotion();
  clearPlots();
  const releases = new Set(state.all.flatMap((f) => f.collections));
  state.mixed = releases.size > 1;
  note("");
  state.selected = null;
  drawCandidates();
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
  useFrames(detector === "all" ? state.all : state.all.filter((f) => f.detector === detector));
}

// --- Engine before and after ---

// Single exposures from Data Release 1, as significance maps.
async function showEngine(side) {
  if (!state.meta) return;
  stop();
  if (state.engine === null) {
    note("Loading engine maps.");
    try {
      state.engine = (await loadEngine(state.id, state.meta.size, state.base)) || false;
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
  // Stacks and differences only make sense within one detector
  if (state.detector === "all" && (state.mode === "stack" || state.mode === "diff")) {
    const mode = state.mode;
    setDetector(frame.detector);
    state.mode = mode;
    drawDetectors();
    draw();
    return;
  }
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
    selected: state.selected,
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
      openTarget(t.id, t.base);
      updateUrl();
    });
    $("targets").append(button);
  }
}

function drawDetectors() {
  $("detectors").innerHTML = "";
  const names = Object.keys(state.meta.stretch);
  for (const detector of names.length > 1 ? ["all", ...names] : names) {
    const button = document.createElement("button");
    button.textContent = detector === "all" ? "All" : detector;
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
  const hoursPerYear = 8766;
  if (state.meta.kind === "asteroid") {
    const c = state.meta.confirmation;
    rows.push(["Object", `${state.meta.name}, a known asteroid (JPL)`]);
    rows.push(["Seen in", `${c.visit_stacks_with_detection} of ${c.visit_stacks} visit stacks over ${c.span_hours} hours`]);
    if (motion.fit) {
      const f = motion.fit;
      rows.push(["Measured", `${(f.rate_arcsec_yr / hoursPerYear).toFixed(1)} +/- ${(f.rate_err_arcsec_yr / hoursPerYear).toFixed(1)} arcsec/hr`]);
    }
    rows.push(["JPL rate", `${c.jpl_rate_arcsec_hr.toFixed(1)} arcsec/hr, V ${c.jpl_vmag}`]);
    rows.push(["Where", state.meta.zenith_note]);
  } else if (state.meta.kind === "live") {
    const list = state.meta.candidates || [];
    rows.push(["Candidates", list.length ? `${list.length}, unchecked` : "none found"]);
    list.forEach((c, i) => {
      const detail = c.kind === "slow" ? `slow, significance ${c.significance}` : `fast, ${c.frames} exposures`;
      rows.push([`c${i + 1}`, `${c.rate} ${c.unit}, ${detail}`]);
    });
    if (list.length) rows.push(["Note", "Not yet checked against catalogues. Most such candidates are artifacts."]);
    if (state.meta.note) rows.push(["Archive", state.meta.note]);
  } else if (motion.fit) {
    const f = motion.fit;
    rows.push(["Measured", `${f.rate_arcsec_yr.toFixed(2)} +/- ${f.rate_err_arcsec_yr.toFixed(2)} arcsec/yr`]);
    rows.push(["Published", `${catalogue.published_rate.toFixed(2)} arcsec/yr`]);
    rows.push(["From", `${f.n_points} visits over ${f.baseline_yr.toFixed(2)} yr`]);
  } else {
    rows.push(["Measured", "not a moving target"]);
  }
  rows.push(["Gaia check", `${alignment.frames_aligned} of ${alignment.frames} frames`]);
  if (alignment.median_scatter_arcsec !== null) {
    rows.push(["Star scatter", `${alignment.median_scatter_arcsec.toFixed(2)} arcsec`]);
  }
  if (catalogue) rows.push(["Markings", "ring: catalogue position. Dashes: catalogue path. Crosses: measured."]);
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
  pickPixel(col, row);
}

// Keyboard way to pick: the selected candidate, else the ringed target, else the centre.
function pickFromKeyboard() {
  if (!state.meta) return;
  const frame = state.frames[state.index];
  let where = [state.meta.ra, state.meta.dec];
  if (state.selected) where = [state.selected.ra, state.selected.dec];
  else if (state.meta.catalogue) where = positionAt(state.meta.catalogue, frame.mjd);
  const [col, row] = skyToImage(state.meta, where[0], where[1]);
  pickPixel(Math.round(col), Math.round(row));
}

function pickPixel(col, row) {
  const size = state.meta.size;
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
    const plate = findPlate(ra, dec);
    return plate ? plate.id : null;
  }
  return (state.targets.find((t) => t.demo) || state.targets[0]).id;
}

// --- Candidates ---

const LADDER = [
  ["flagged", "1. Flagged: did not pass every automatic check"],
  ["passed_checks", "2. Passed automatic checks"],
  ["community_confirmed", "3. Confirmed by community"],
  ["team_reviewed", "4. Reviewed by team"],
];
const OUTCOMES = {
  known: "Outcome: known object",
  artifact: "Outcome: artifact",
  unexplained: "Outcome: unexplained candidate",
};

async function refreshCandidates() {
  const { rows, live } = await loadCandidates();
  state.candidates = rows;
  state.candidatesLive = live;
  drawCandidates();
}

function candidatesHere() {
  if (!state.meta) return [];
  const half = (state.meta.fov_deg * 3600) / 2;
  return state.candidates.filter((c) => {
    const [east, north] = project(c.ra, c.dec, state.meta.ra, state.meta.dec);
    return Math.max(Math.abs(east), Math.abs(north)) < half;
  });
}

function drawCandidates() {
  const here = candidatesHere();
  const where = state.candidatesLive ? "the shared candidate list" : "the copy stored with the site (votes are off)";
  $("cand-source").textContent = here.length
    ? `${here.length} from ${where}. Each came out of the engine on real exposures; the status says what the checks found.`
    : "The engine has no stored candidate on this plate.";
  $("cand-list").innerHTML = "";
  for (const c of here) {
    const button = document.createElement("button");
    const status = c.status.replace("_", " ");
    button.textContent = `${c.checks.summary.label} [${status}]`;
    button.setAttribute("aria-pressed", String(state.selected === c));
    button.addEventListener("click", () => selectCandidate(state.selected === c ? null : c));
    $("cand-list").append(button);
  }
  if (state.selected && !here.includes(state.selected)) state.selected = null;
  drawCard();
}

function selectCandidate(candidate) {
  state.selected = candidate;
  if (candidate && candidate.checks.summary.kind === "fast" && state.mode !== "engine") {
    // Jump to the frame closest in time to the track
    stop();
    let best = 0;
    state.frames.forEach((f, i) => {
      if (Math.abs(f.mjd - candidate.checks.summary.mjd) < Math.abs(state.frames[best].mjd - candidate.checks.summary.mjd)) best = i;
    });
    state.index = best;
  }
  $("vote-result").hidden = true;
  drawCandidates();
  draw();
}

function drawCard() {
  const c = state.selected;
  $("cand-card").hidden = !c;
  if (!c) return;
  const summary = c.checks.summary;
  $("cand-title").textContent = summary.label;
  const also = summary.also_seen_in.length ? `, also found in ${summary.also_seen_in.join(", ")}` : "";
  $("cand-motion").textContent = `${formatCoord(c.ra, c.dec)}. ${summary.motion}. ${summary.field}, ${summary.detector}${also}, ${c.frames_used} exposures.`;

  const ladder = $("cand-ladder");
  ladder.innerHTML = "";
  for (const [key, text] of LADDER) {
    const li = document.createElement("li");
    li.textContent = c.status === key ? `${text} (now)` : text;
    if (c.status === key) li.className = "now";
    ladder.append(li);
  }
  const outcome = document.createElement("li");
  if (OUTCOMES[c.status]) {
    const how = c.status === "known" ? ", set by the automatic catalogue check" : ", set by the team";
    outcome.textContent = `${OUTCOMES[c.status]} (now${how})`;
    outcome.className = "now";
  } else {
    outcome.textContent = "Outcome: known object, artifact or unexplained candidate. Not decided yet.";
  }
  ladder.append(outcome);

  const list = $("cand-checks");
  list.innerHTML = "";
  for (const check of c.checks.items) {
    const li = document.createElement("li");
    const tag = document.createElement("span");
    tag.className = `tag ${check.result}`;
    tag.textContent = { na: "n/a", warn: "note" }[check.result] || check.result;
    li.append(tag, `${check.title}. ${check.reason}`);
    list.append(li);
  }

  const canVote = state.candidatesLive && c.id != null && c.checks.items.length > 0 && c.status !== "known";
  const real = c.real_votes || 0;
  const artifact = c.artifact_votes || 0;
  let votes = `Community votes: ${real} real, ${artifact} artifact.`;
  if (c.status === "known") votes += " Voting is closed because this is a known object.";
  else if (!state.candidatesLive) votes += " Voting is unavailable while the shared list cannot be reached.";
  $("cand-votes").textContent = votes;
  $("b-vote-real").disabled = !canVote;
  $("b-vote-artifact").disabled = !canVote;
}

async function vote(kind) {
  if (!state.selected) return;
  $("b-vote-real").disabled = true;
  $("b-vote-artifact").disabled = true;
  const id = state.selected.id;
  const message = await castVote(id, kind);
  await refreshCandidates();
  state.selected = state.candidates.find((c) => c.id === id) || null;
  drawCandidates();
  $("vote-result").textContent = message;
  $("vote-result").hidden = false;
}

function download(name, blob) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

// Evidence card: what the plate shows and what the checks said. Nothing is sent anywhere.
function exportEvidence(kind) {
  const c = state.selected;
  if (!c) return;
  const name = `tombaugh-candidate-${c.id ?? "local"}`;
  if (kind === "png") {
    canvas.toBlob((blob) => download(`${name}.png`, blob));
    return;
  }
  const frame = state.frames[state.index];
  const card = {
    tool: "Tombaugh",
    note: "A candidate report, not a confirmed object. Tombaugh submits nothing to any agency.",
    exported_utc: new Date().toISOString(),
    candidate: c,
    plate: { name: state.meta.name, ra: state.meta.ra, dec: state.meta.dec, fov_deg: state.meta.fov_deg },
    frame_shown: { date: frame.date, detector: frame.detector, wavelength_um: frame.wavelength_um, mode: state.mode },
    link: location.href,
    where_experts_go: {
      slow_movers: "https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9",
      asteroids_and_comets: "https://www.minorplanetcenter.net/",
    },
  };
  download(`${name}.json`, new Blob([JSON.stringify(card, null, 2)], { type: "application/json" }));
}

// --- Public sky map ---

async function refreshSkyMap() {
  const searches = await loadSearches();
  const plates = state.targets.filter((t) => t.centre);
  const patches = drawSkyMap($("skymap"), searches, plates);
  if (searches === null) {
    $("sky-count").textContent = "The shared map cannot be reached right now. Circles are the stored plates.";
    $("skymap").setAttribute("aria-label", "All-sky map showing the stored plates only");
    return;
  }
  $("sky-count").textContent = `${patches} patches of sky searched by the public, from ${searches.length} lookups. Squares are 3 degree patches; circles are the stored plates. No locations are kept.`;
  $("skymap").setAttribute("aria-label", `All-sky map: ${patches} patches searched by the public`);
}

// --- Your sky ---

function findPlate(ra, dec) {
  for (const t of state.targets) {
    if (!t.centre) continue;
    const [east, north] = project(ra, dec, t.centre[0], t.centre[1]);
    if (Math.max(Math.abs(east), Math.abs(north)) < (t.centre[2] * 3600) / 2) return t;
  }
  return null;
}

function addAction(label, run) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", run);
  $("above-actions").append(button);
}

// The zenith is worked out here in the browser. Only the rounded patch is used.
function lookUp(place) {
  const [ra, dec] = zenith(place.lat, place.lon, new Date());
  const [fieldRa, fieldDec] = fieldCentre(ra, dec);
  // Adds a coarse patch to the public map; never the place itself
  logSearch(fieldRa, fieldDec, place.label === "you" ? "overhead" : "manual").then((ok) => ok && refreshSkyMap());
  $("above-actions").innerHTML = "";
  let text = `Straight above ${place.label} right now: ${formatCoord(fieldRa, fieldDec)}. `;
  const plate = findPlate(ra, dec);
  if (plate) {
    text += "A plate is stored for this patch. It shows what SPHEREx recorded there on earlier dates.";
    openTarget(plate.id, plate.base);
  } else {
    text += "No plate is stored for this patch. ";
    if (state.apiOn) {
      text += "Tombaugh can build one from the SPHEREx archive, which takes a few minutes.";
      addAction("Build this patch", () => startLive(fieldRa, fieldDec));
    } else {
      text += "Live lookups are off right now.";
    }
    const demo = state.targets.find((t) => t.demo);
    if (demo) {
      text += " The stored demo plate is a patch that passes over Singapore once a day.";
      addAction(demo.name, () => openTarget(demo.id));
    }
  }
  $("above-result").textContent = text;
  $("above-result").hidden = false;
}

function lookUpTyped() {
  const place = parsePlace($("place").value);
  if (place) {
    lookUp(place);
  } else {
    $("above-actions").innerHTML = "";
    $("above-result").textContent =
      "Place not recognised. Type a large city, or latitude and longitude such as 1.35, 103.82.";
    $("above-result").hidden = false;
  }
}

function lookUpHere() {
  const fallback = () => {
    $("above-result").textContent = "Location was not available, so the place in the box is used instead.";
    $("above-result").hidden = false;
    lookUpTyped();
  };
  if (!navigator.geolocation) return fallback();
  navigator.geolocation.getCurrentPosition(
    (pos) => lookUp({ lat: pos.coords.latitude, lon: pos.coords.longitude, label: "you" }),
    fallback,
    { maximumAge: 600000, timeout: 8000 }
  );
}

// --- Live lookup ---

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function startLive(ra, dec) {
  stop();
  note("Asking the back end to build this patch.");
  try {
    const res = await fetch(`${API_URL}/api/field`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ra, dec, fov_deg: LIVE_FOV_DEG, detector: params.get("det") }),
    });
    let job = await res.json();
    if (!res.ok) throw new Error(job.detail || `status ${res.status}`);
    while (job.status === "queued" || job.status === "running") {
      note(`${job.step} Step ${job.steps_done + 1} of ${job.steps_total}.`);
      await sleep(2000);
      job = await (await fetch(`${API_URL}/api/field/${job.job_id}`)).json();
    }
    if (job.status !== "done") throw new Error(job.error || "the job stopped");
    const base = `${API_URL}${job.base_url}`;
    if (!state.targets.some((t) => t.id === job.field_id)) {
      state.targets.push({ id: job.field_id, name: job.name, centre: job.centre, base });
    }
    await openTarget(job.field_id, base);
    // The back end has just stored this plate's candidates
    refreshCandidates();
  } catch (err) {
    note(`The live lookup did not finish: ${err.message}. Stored plates still work.`);
  }
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
  $("b-above").addEventListener("click", lookUpHere);
  $("b-vote-real").addEventListener("click", () => vote("real"));
  $("b-vote-artifact").addEventListener("click", () => vote("artifact"));
  $("b-export-json").addEventListener("click", () => exportEvidence("json"));
  $("b-export-png").addEventListener("click", () => exportEvidence("png"));
  $("b-place").addEventListener("click", lookUpTyped);
  $("place").addEventListener("keydown", (event) => {
    if (event.key === "Enter") lookUpTyped();
  });

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target instanceof HTMLInputElement) return;
    if (event.key === "Enter" && event.target === canvas) {
      event.preventDefault();
      pickFromKeyboard();
      return;
    }
    if (event.target instanceof HTMLButtonElement && event.key === " ") return;
    // Space on the "How to use this" heading opens and closes it
    if (event.target.tagName === "SUMMARY" && event.key === " ") return;
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
  if (!API_URL) {
    el.textContent = "off. Stored plates still work.";
    return;
  }
  try {
    const body = await (await fetch(`${API_URL}/api/health`)).json();
    state.apiOn = body.status === "ok";
    el.textContent = state.apiOn ? "on" : "off";
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
  const apiChecked = checkApi();
  try {
    state.targets = await loadIndex();
  } catch {
    note("Precomputed plates are missing.");
    return;
  }
  const id = await chooseTarget();
  drawTargets();
  refreshCandidates();
  refreshSkyMap();
  if (!id) {
    // A shared link to a patch without a stored plate: build it if the back end is up
    await apiChecked;
    const [ra, dec] = fieldCentre(parseFloat(params.get("ra")), parseFloat(params.get("dec")));
    if (state.apiOn) {
      await startLive(ra, dec);
    } else {
      note("No plate is stored for this position, and live lookups are off right now.");
    }
    return;
  }
  await openTarget(id);
}

start();
