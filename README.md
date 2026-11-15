# Tombaugh

**What's moving above you?**

Clyde Tombaugh found Pluto in 1930 by flicking between two photographs of the same stars and spotting the one that moved.

Tombaugh is a public web tool that does the same with images from NASA's SPHEREx space telescope. It finds the patch of sky straight above you, shows how that patch changed between SPHEREx visits, labels the movers it can name, and puts anything it cannot name through a list of checks before anyone is asked to look at it. It reports candidates only.

Built for the NASA Space Apps Challenge 2026, challenge "Planet X and SPHEREx".

- **Live site:** _to be added by the team_
- **Back end:** _to be added by the team_

Every number in this file is printed by `python -m scripts.validate` (run from `backend/`), which names the script that regenerates each one from the SPHEREx data.

## What you can do with it

- **See your sky.** Press "What's moving above you?" or type a city or coordinates. The zenith is worked out in your browser, so your location never leaves your device; only a patch rounded to 0.2 degrees is used. The plate shows that patch as SPHEREx recorded it on earlier dates. It is not a live view.
- **Blink it.** Play the visits, step through them, blink two frames, stack them, or subtract one from another. Plate view shows the sky as a negative, as astronomers did in 1930; Sky view shows it dark.
- **Compare before and after.** For four fields, switch between a plain difference and the engine's residual.
- **Click a point** for its spectrum and light curve across the visits.
- **Open a candidate** to see its checklist, its status, and the votes. Vote "looks real" or "looks like an artifact" without logging in.
- **Share a link.** `?ra=&dec=&fov=&det=&mode=` reopens the same view; add `&view=sky` for Sky view and `&embed=1` for a bare player. `mode` is `frames`, `diff`, `stack`, `before` or `after`.

Keys: space play, arrows step, B blink, D difference, S stack, E before or after, P plate or sky, G Gaia stars. With the plate focused, Enter reads the spectrum at the marked object.

## The three ideas, with what we measured

All engine numbers use SPHEREx Data Release 1 only, so mixed calibrations cannot add false residuals.

### 1. The engine: per-pixel measured noise, and a per-pixel time term

**The problem.** SPHEREx pixels are 6.15 arcsec across, larger than a star image, so the same star lands on the pixel grid differently in every exposure. Subtract one exposure from another and every star core leaves a false residual.

**What works.** We measure how much each pixel scatters across all exposures of a field and judge each residual against that pixel's own noise. Mean residual peaks per exposure at 5 sigma:

| Field, detector | Exposures | Plain difference, image noise | Engine, per-pixel noise |
|---|---|---|---|
| WISE 0855, D5 | 48 | 12.08 | 2.25 |
| WISE 0855, D6 | 45 | 7.40 | 4.04 |
| Barnard's Star, D3 | 38 | 182.89 | 0.00 |
| Barnard's Star, D4 | 41 | 119.07 | 4.54 |
| Epsilon Indi B, D2 | 64 | 53.45 | 0.61 |
| Epsilon Indi B, D3 | 60 | 44.27 | 0.45 |

"Plain difference" is each exposure minus the median of all exposures.

**What did not work.** Our first idea was that the false residuals come from SPHEREx seeing each star at a different wavelength on every visit, and that fitting each pixel's brightness against wavelength would cancel them. We built and tested that fit. It is stable, but it did not help on its own: judged against the image noise, the counts barely move (53.45 before and 51.05 after on Epsilon Indi B, D2). On three bright stars in that field, total brightness changed 2.6 to 6.6% between exposures while the centre pixel changed 22.6 to 28.0%. The per-pixel noise does the work, and it does the same on a plain median difference (0.69 on that field against the engine's 0.61). The wavelength term stays in the fit only so that a spectral slope is not mistaken for a change with time.

**Slow movers, found blind.** Nearby stars and brown dwarfs move by less than one star width over the data, so they never appear as a separate spot. We add a straight line in time to each pixel's fit. A slow mover fades behind itself and brightens ahead, and fitting that pattern against the image gradient gives a velocity, with its significance calibrated on the field's own stars. No catalogue is used to find these; a catalogue is consulted afterwards to name them.

| Target | Detector | Found blind | Significance | Other candidates in the field |
|---|---|---|---|---|
| WISE 0855-0714 | D5 | yes | 6.0 | 0 |
| WISE 0855-0714 | D6 | yes | 8.6 | 0 |
| Epsilon Indi B | D2 | yes | 12.8 | 0 |
| Epsilon Indi B | D3 | yes | 13.3 | 0 |
| Barnard's Star | D3 | no | | 1 |
| Barnard's Star | D4 | no | | 2 |

**Fast movers, injection test.** We planted synthetic moving point sources (5 to 60 arcsec per hour) into copies of the exposures, in memory only, and counted how many were linked into a track of three or more exposures. 90 synthetic sources per brightness level over three fields:

| Peak signal to noise | 5 | 7 | 10 | 15 | 25 |
|---|---|---|---|---|---|
| Linked | 31% | 67% | 77% | 84% | 87% |

In the real, un-injected data the same search returned 8 fast tracks over 0.24 square degrees, about 33 per square degree. None of the 8 matches a known asteroid or comet in JPL Small-Body Identification, so all 8 are treated as false alarms. The synthetic runs produced 35 further tracks that matched no planted source; none matches a known object either (15 are one real-data track reappearing in every run, 20 contain one or two detections of a planted source).

**Motion and alignment measured from the images.** Straight-line fits to centroids on per-visit stacks:

| Target | Measured (arcsec/yr) | Published | Visits | Baseline |
|---|---|---|---|---|
| WISE 0855-0714 | 7.51 +/- 0.57 | 8.15 | 34 | 1.02 yr |
| Barnard's Star | 11.04 +/- 0.82 | 10.39 | 50 | 1.05 yr |
| Epsilon Indi B | 4.57 +/- 0.08 | 4.70 | 70 | 1.44 yr |

With a parallax term, Epsilon Indi B gives 4.64 +/- 0.08 arcsec/yr and a parallax of 0.29 +/- 0.05 arcsec.

Every frame is checked against Gaia DR3 stars moved to the frame date. Across the five showcase fields (619 frames) the header positions wander by 0.14 to 0.26 arcsec from frame to frame, and single stars scatter by 0.34 to 0.53 arcsec about the fitted correction. The `FINAST` header flag is 0 in all 619 frames, so we do not filter on it.

### 2. The hook: "What's moving above you?"

- **The lookup** turns a place and time into the point straight overhead: right ascension is the local sidereal time and declination is the latitude, corrected for precession since 2000. It runs in the browser; the back end has the same calculation in astropy.
- **The demo plate, "Above Singapore, 2025-12-20",** is a 0.3 degree patch at Dec +1.54, 0.19 degrees from Singapore's zenith declination, so it passes almost straight overhead once a day. It contains asteroid 120 Lachesis (V 13.4).
  - Lachesis is seen in 8 of 8 visit stacks (22 exposures, detectors D1, D2, D4, D5) over 17.8 hours, moving 487.8 arcsec across the plate.
  - Measured rate 27.34 +/- 0.05 arcsec/hr; JPL gives 27.37.
  - The engine's blind fast-mover search on D2 returns exactly one track, and it is Lachesis (7 exposures, 27.33 arcsec/hr). Mean residual peaks per exposure go from 64.88 to 0.97.
  - **The asteroid was chosen by hand.** JPL returned 38 positions of asteroids brighter than V 17 in the zenith strips, but IRSA's image search was down while we built this, so we could not count exposures for each one. We picked Lachesis because it passed 0.35 to 0.6 degrees from a point whose exposure list we had already saved.
- **Other positions** are built on request by the back end (one detector, up to 60 exposures, at most 0.3 degrees), with progress shown step by step. The stored plates work with the back end off.

### 3. A careful candidate pipeline

Anything the engine finds goes through eight automatic checks before a person is asked to look:

1. Not a known object: Gaia DR3 and SIMBAD moved to the frame date, JPL Small-Body Identification at the track time.
2. No bad pixels in the aperture (cosmic ray, persistence, ghost, saturation, edge). The outlier flag is ignored, because the pipeline sets it on moving objects.
3. Astrometry checked in the frames used. `FINAST` is 0 everywhere in DR1, so this reports our own Gaia alignment.
4. Seen at 5 sigma or more in at least three frames.
5. Positions on a straight line at a steady rate.
6. Seen in more than one detector where coverage allows.
7. Star-like, and not in the halo of a bright star.
8. Survives the engine.

A further warning fires when several tracks come from one night with only three exposures each.

Each candidate carries a status: Flagged, Passed automatic checks, Confirmed by community, Reviewed by team, then Known object, Artifact or Unexplained. The checks can only set Flagged, Passed or Known. The later steps belong to people.

**What the checks said about the real engine outputs.** The engine produced 16 candidates in the three mover fields and the Singapore field (after merging the same object seen in two detectors):

- **3 known:** asteroid 120 Lachesis (JPL), WISE 0855-0714 and Epsilon Indi B (both SIMBAD), each 1 arcsec from the catalogue position.
- **11 flagged:** three slow candidates in the halo of Barnard's Star, six fast tracks from one night in the Barnard's Star field, and two fast tracks with flagged pixels in the aperture.
- **2 passed automatic checks:** two fast tracks of three exposures each. Passing means worth a human look, nothing more.

Of the eight false-alarm tracks from the injection test, seven are flagged and one passed. The shared table holds 15 of these as rows (two candidates 20 arcsec apart are stored as one), plus 9 rows written by a live lookup we ran as a test.

Votes are anonymous, one per device per candidate. The public map shows only 3 degree patches of sky that visitors have looked up. Tombaugh never sends anything to an agency or survey; candidate cards point experts to [Backyard Worlds: Planet 9](https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9) for slow movers and the [Minor Planet Center](https://www.minorplanetcenter.net/) for asteroids and comets.

## How it works

1. **Find the exposures.** IRSA's image search lists every SPHEREx Level 2 exposure covering a position.
2. **Cut out the patch.** Each cutout is downloaded with its flags, variance, zodiacal light and wavelength planes. The download stops before the large PSF extension; the small wavelength table is the same for every cutout of a detector (checked on 30 full cutouts) and is fetched once.
3. **Clean.** Subtract the zodiacal light and the leftover background; mask flagged pixels, but never for the source or outlier flags.
4. **Align.** Match Gaia DR3 stars, moved to the exposure date, and fit a small shift, rotation and scale per exposure.
5. **Resample** every exposure onto one north-up grid of 3 arcsec pixels and stack each visit with outlier rejection.
6. **Run the engine** on the single exposures of one detector: per-pixel fit in wavelength and time, per-pixel noise, residual detection, track linking, slow-mover search.
7. **Check** each candidate and store it.

The front end is plain HTML, CSS and JavaScript with a canvas player and no build step. The back end is FastAPI in one Docker image.

## Honest limits

- **Engine rates are low and detection-only.** The blind slow-mover search gets the direction right, but its rates are 25 to 55% below the published values (5.45 and 6.23 arcsec/yr for WISE 0855 against 8.15; 2.21 and 3.42 for Epsilon Indi B against 4.70). Use the centroid fits for rates.
- **Barnard's Star is not found by the blind search.** Its core is saturated and masked in every exposure. Its motion is measured from the unsaturated wings, which is why its error is the largest.
- **The synthetic sources are idealised.** They are round blobs without the exposure-to-exposure sampling changes real stars show, so the recovery fractions are somewhat optimistic.
- **The false-alarm figure is an upper bound,** and the linker is permissive: a live lookup of one ordinary field stored 9 more candidates, 3 of which passed the automatic checks.
- **The wavelength fit does not remove residuals by itself.** See above.
- **Single-star alignment scatter (0.34 to 0.53 arcsec) is above our 0.3 arcsec target.**
- **IRSA's image search was down for the last hours of the build.** The demo asteroid was chosen by hand for that reason, and the live lookup was tested only through its fallback, which reuses a saved exposure list from a point within 0.6 degrees and says so on the plate. The ordinary path, with the search answering, is untested.
- **Only two detectors per showcase target** are built, and deep fields are capped at 80 exposures per detector.
- **Live plates do not label known asteroids on the image**; the candidate checklist does the naming.
- **Reduced-motion behaviour** (no autoplay, slower blink) is implemented but was not tested with the browser setting switched on.
- **Nothing here is a confirmed new object.**

## Run it and reproduce the numbers

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt
cd backend
python -m uvicorn app.main:app --port 8000
```

Serve the front end from another terminal with `python -m http.server 5500 --directory docs` and open `http://localhost:5500`. The back end reads `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from `backend/.env` (see `backend/.env.example`).

| Script (run as `python -m scripts.<name>` from `backend/`) | What it produces |
|---|---|
| `validate` | Prints every number in this file from the result files below |
| `build_showcase` | Plates, Gaia alignment and motion fits for the five showcase targets |
| `run_engine` | Before and after counts, blind slow-mover search, injection test |
| `measure_sampling` | Star brightness against single-pixel scatter |
| `check_tracks` | Fast tracks against JPL Small-Body Identification |
| `find_demo_asteroid`, `build_demo` | JPL strip search and the Singapore demo plate |
| `build_engine_view` | Before and after images for the viewer |
| `seed_candidates` | Checks on the real engine outputs, written to Supabase |
| `check_wave_table` | Wavelength table compared across 30 full cutouts |
| `check_rls` | Twelve row level security tests with the publishable key |
| `python -m unittest discover -s tests -t .` | 17 unit tests |

Synthetic data appears only in the injection test and the unit tests, is labelled there, and is never written to the plates or the candidates table.

## Deploying

- **Back end:** `backend/Dockerfile` builds one image, pushed to GitHub Container Registry and run on Azure Container Apps (scale to zero, at most one replica). The same image runs on Hugging Face Spaces. `ALLOWED_ORIGINS` limits CORS to the site's domain; the Supabase values are passed as secrets.
- **Front end:** Vercel serves the `docs/` folder as a static site. The back-end address is one line in `docs/config.js`.

## Data, services and software

**Data**

- **SPHEREx** Level 2 spectral images, Data Release 1 (and Quick Release 3 in some showcase plates), from the NASA/IPAC Infrared Science Archive (IRSA): image search (SIA2) and the cutout service. _Archive DOI and SPHEREx acknowledgement text: to be copied by the team from the IRSA SPHEREx page._ This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National Aeronautics and Space Administration and operated by the California Institute of Technology.
- **Gaia DR3** (ESA Gaia mission, processed by the Gaia Data Processing and Analysis Consortium), queried from the ESA Gaia Archive and, when that did not answer, from the Gaia partner archive at the Leibniz Institute for Astrophysics Potsdam (gaia.aip.de).
- **SIMBAD**, operated at CDS, Strasbourg, France, queried through its TAP service and, when that did not answer, through the mirror at the Harvard-Smithsonian Center for Astrophysics (simbad.harvard.edu).
- **JPL Small-Body Identification API** (NASA Jet Propulsion Laboratory, Solar System Dynamics) for known asteroids and comets.
- **Published positions and proper motions** of Barnard's Star, Epsilon Indi B and WISE 0855-0714, used only to centre the showcase fields and place search windows.

**Services**

- **Supabase** for the candidates, votes and sky-search tables.
- **Vercel** for the static site.
- **Azure Container Apps** for the back end, with **GitHub Container Registry** for the image and **Docker** to build it.
- **Google Fonts** for Fraunces and IBM Plex Mono.

**Software**

- Python 3.12 with **NumPy**, **SciPy**, **Astropy**, **Requests**, **FastAPI** (with Pydantic and Starlette) and **Uvicorn**. **Black** formats the code.
- The front end uses no JavaScript libraries.

Aladin Lite, CDS Sesame, astroquery, pyvo, reproject and photutils were planned but are not used.

## Use of AI

We used Claude (Anthropic) to help develop our method and to write and debug much of the code. Our team chose the challenge and approach, studied competing solutions, directed the work, reviewed and tested all code, ran every validation ourselves, and created the presentation.

## Team

_Names and roles to be added by the team._
