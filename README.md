# Tombaugh

**What's moving above you?**

Clyde Tombaugh found Pluto in 1930 by flicking between two photographs of the same stars and spotting the one that moved. Tombaugh is a public web tool that does the same with images from NASA's SPHEREx space telescope, for the patch of sky above you.

Built for the NASA Space Apps Challenge 2026, challenge "Planet X and SPHEREx".

This README is a working draft. The live link, usage notes, references, AI statement and team section are added in the final phase.

## What the engine does, and what we measured

Every number below comes from a script in this repo and uses SPHEREx Data Release 1 only, so mixed calibrations cannot add false residuals.

### 1. Per-pixel measured noise removes the false residuals

SPHEREx pixels are 6 arcsec across, larger than a star image, so the same star lands on the pixel grid differently in every exposure. Subtract one exposure from another and every star core leaves a false residual.

We measure how much each pixel scatters across all exposures of a field and judge each residual against that pixel's own noise. Mean residual peaks per exposure at 5 sigma (`backend/scripts/run_engine.py`):

| Field, detector | Exposures | Plain difference, image noise | Engine, per-pixel noise |
|---|---|---|---|
| WISE 0855, D5 | 48 | 12.1 | 2.25 |
| WISE 0855, D6 | 45 | 7.4 | 4.04 |
| Barnard's Star, D3 | 38 | 183 | 0.00 |
| Barnard's Star, D4 | 41 | 119 | 4.54 |
| Epsilon Indi B, D2 | 64 | 53 | 0.61 |
| Epsilon Indi B, D3 | 60 | 44 | 0.45 |

"Plain difference" is each exposure minus the median of all exposures. The viewer has a Before / After switch that shows both for these three fields.

**What did not work.** Our first idea was that the false residuals come from SPHEREx seeing each star at a different wavelength on every visit, and that fitting each pixel's brightness against wavelength would cancel them. We built and tested that fit. It is stable, but it did not help on its own: with the image noise as the yardstick the counts stayed the same (for example 53 before and 51 after on Epsilon Indi B, D2). On three bright stars a star's total brightness changed 2.6 to 6.6% with wavelength across the detector, while a single pixel on the star changed 21 to 28% from sampling alone. The per-pixel noise does the work, and it does the same on a plain median difference. The wavelength term stays in the fit only so that a spectral slope is not mistaken for a change with time.

### 2. A per-pixel time term finds slow movers blind

Nearby stars and brown dwarfs move by less than one star width over the data, so they never show up as a separate spot in a difference image. We add a straight line in time to each pixel's fit. A source that moves slowly fades behind itself and brightens ahead, and a fit of that pattern against the image gradient gives a velocity. The significance is calibrated on each field's own stars. No catalogue is used to find the candidates; the catalogue is consulted afterwards to see which candidate is the known target.

| Target | Detector | Found blind | Significance | Other candidates in the field |
|---|---|---|---|---|
| WISE 0855-0714 | D5 | yes | 6.0 | 0 |
| WISE 0855-0714 | D6 | yes | 8.6 | 0 |
| Epsilon Indi B | D2 | yes | 12.8 | 0 |
| Epsilon Indi B | D3 | yes | 13.3 | 0 |
| Barnard's Star | D3 | no | | 1 |
| Barnard's Star | D4 | no | | 2 |

### 3. Motion and alignment measured from the images

Straight-line fits to centroids on per-visit stacks (`backend/scripts/build_showcase.py`):

| Target | Measured (arcsec/yr) | Published | Visits | Baseline |
|---|---|---|---|---|
| WISE 0855-0714 | 7.51 +/- 0.57 | 8.15 | 34 | 1.02 yr |
| Barnard's Star | 11.04 +/- 0.82 | 10.39 | 50 | 1.05 yr |
| Epsilon Indi B | 4.57 +/- 0.08 | 4.70 | 70 | 1.44 yr |

Every frame is checked against Gaia DR3 stars moved to the frame date. Across the five showcase fields the header positions wander by 0.14 to 0.26 arcsec from frame to frame, and single stars scatter by 0.34 to 0.53 arcsec about the fitted correction.

### 4. Injection test for fast movers

We planted synthetic moving point sources (5 to 60 arcsec per hour) into copies of the exposures, in memory only, and counted how many the engine linked into a track of three or more exposures. 90 synthetic sources per brightness level over three fields:

| Peak signal to noise | 5 | 7 | 10 | 15 | 25 |
|---|---|---|---|---|---|
| Linked | 31% | 67% | 77% | 84% | 87% |

In the real, un-injected data the same search returned 8 fast tracks over 6 runs covering 0.24 square degrees in total, about 33 per square degree. We checked all 8 against JPL Small-Body Identification (geocentric, V brighter than 21, 30 arcsec match radius, `backend/scripts/check_tracks.py`): none matches a known asteroid or comet, so all 8 are treated as false alarms.

## Honest limits

- **Engine rates are low and detection-only.** The blind slow-mover search gives the right direction, but its rates are 25 to 55% below the published values (for example 5.45 and 6.23 arcsec/yr for WISE 0855 against 8.15). Use the centroid fits in section 3 for rates.
- **Barnard's Star is not found by the blind search.** Its core is saturated and masked in every exposure. Its motion in section 3 is measured from the unsaturated wings.
- **The synthetic sources are idealised.** They are round blobs without the exposure-to-exposure sampling changes real stars show, so the recovery fractions are somewhat optimistic.
- **The false-alarm figure is an upper bound.** It counts every fast track in real data as false.
- **Single-star alignment scatter is above our 0.3 arcsec target.**
- **Nothing here is a confirmed new object.** The tool reports candidates only.
