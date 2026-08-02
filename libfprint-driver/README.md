# libfprint driver for the EgisTec EH576 (1c7a:0576)

A **libfprint driver** for the EH576, written in C against current libfprint
master and validated end-to-end on real hardware (Lenovo Yoga 7 16IRL8):
device init, finger detection, capture, 8-stage enrollment, and verification
all run through the standard libfprint API (`examples/enroll`,
`examples/verify`).

**Status: the protocol and capture side work; matching does not yet.** The
driver reliably produces clean fingerprint images and completes enrollment and
verification flows, but the correlation matcher's genuine and impostor scores
overlap, so it cannot yet be trusted to tell fingers apart — see "Matching
does not currently work reliably" below for the measurements and for what
needs to change. Use it as a working capture/protocol foundation and a
matching problem to attack, not as a drop-in authentication device.

The protocol layer is built directly on this project's findings (INIT/REPEAT
sequences, variance-based finger detection, the gain register) plus the vendor
preprocessing reverse-engineered from the Windows driver.

## Files

| File | Contents |
|---|---|
| `egis0576.c` | The driver: USB protocol, init/capture state machines, enrollment, identification |
| `egis0576.h` | Init/repeat packet tables and device constants |
| `egis_match.c` | Correlation matcher (included by `egis0576.c`; also builds standalone as an offline eval tool) |

## Why this is not an FpImageDevice driver

The obvious approach — an `FpImageDevice` driver that hands frames to
libfprint's NBIS pipeline — **cannot work on this sensor**, and it's worth
recording why:

- bozorth3 refuses to compute a match if either side has fewer than 10
  minutiae (`MIN_COMPUTABLE_BOZORTH_MINUTIAE`, nbis/include/bozorth.h).
- A 70x57 frame from this sensor yields **8-19 minutiae**, and NBIS's
  extractor discards anything whose analysis window touches the image border,
  which on an image this small is most of the print. Every verify scores an
  automatic 0.
- Padding the image with a neutral border (minutiae 5 → 19) and hand-rolled
  2x upscaling help, but not enough to clear the floor reliably.

(Also of practical note: `fpi_image_resize()` segfaults on 70px-wide frames —
it hands pixman a stride equal to the width, and pixman requires stride % 4 == 0.)

The vendor's own Windows engine doesn't use minutiae either — it matches ridge
structure ("skeletons") on the host. This driver does the same: it is a plain
`FpDevice` with driver-managed enrollment and matching.

## How it works

- **Detection** runs at the sensor's default gain: poll frames, variance > 12
  means finger (this project's proven test), then hold until the press
  *settles* (peak variance) so a first-contact partial print is never used.
- **The match frame** is captured at gain 6 (register 0x12) — ~2.4x the ridge
  SNR of the default. The sensor must be re-armed (REPEAT sequence) between
  the gain write and the image request, or it returns a blank frame.
- **Enrollment** collects 8 coverage-gated presses (coherence mask must cover
  >= 55% of the frame) and stores the raw frames in the print's `fpi-data`.
- **Verification** enhances the probe (3x3 box mean minus 9x9 box mean — the
  vendor's own background subtraction, kills fixed-pattern noise with no
  stored calibration), masks to coherent-ridge blocks (structure-tensor
  coherence, from the vendor's `qty` metric), and scores translation-searched
  normalized cross-correlation against each enrolled frame, best-of-8.

## Matching does not currently work reliably — read this before trusting it

**The correlation matcher does not separate genuine presses from impostors on
this sensor.** This is measured, not suspected, and it is the honest headline:
the capture side of this driver is solid, the matching side is an open problem.

Numbers from a controlled run (one unit, one user, every press explicitly
prompted and labeled at press time — see "Evaluation harness" below): 8
enrolled right-index templates, then 5 probes each of right index (genuine),
right thumb, and left index (impostors), scored best-of-8:

| probe | scores |
|---|---|
| genuine (right index) | 0.350, 0.392, 0.451, 0.798, 0.981 |
| impostor (right thumb) | 0.275, 0.295, 0.338, 0.353, 0.364 |
| impostor (left index) | 0.272, 0.281, 0.374, 0.447, 0.456 |

The worst genuine press (0.350) scores **below** the best impostor (0.456), so
no threshold classifies this set correctly — the margin is -0.106. Genuine
scores also swing enormously with placement (0.35 to 0.98 on the same finger).

Why: on a 70x57 patch almost all ridges are near-parallel, so global
correlation largely measures ridge *orientation and spacing*, which any two
fingertips share when pressed at a similar angle. The identity information —
ridge endings and bifurcations, and how they're arranged — is exactly what
correlation discards.

Approaches tried that do **not** fix it (don't spend time re-deriving these):
multi-template consensus, peak-to-sidelobe ratio of the correlation surface,
local-tile agreement, and top-3 score fusion. All produce overlapping genuine
and impostor distributions. **The feature has to change, not the score
fusion.** The two promising directions:

1. **Mosaic the enrolled frames** into a larger composite template. That may
   clear NBIS/bozorth3's 10-minutiae floor on the template side and let the
   standard libfprint matcher do the work.
2. **A real minutiae + orientation-field matcher** (SourceAFIS-style).

Contributions very welcome — the matcher is deliberately isolated in
`egis_match.c` behind a two-function interface (`em_frame_compute` /
`em_match`), so it can be replaced without touching the USB or state-machine
code.

*(An earlier revision of this file quoted "genuine 0.47-0.89, impostors
0.11-0.21". Those came from an unlabeled ad-hoc session where presses were
driven by a timer rather than confirmed per press; the table above supersedes
them.)*

## Evaluation harness

Trustworthy numbers need labeled presses. `test_matching.py` in the repo root
prompts for each press by name ("Press 3/8 — RIGHT INDEX"), waits for you,
reports captured/rejected with coverage, forces a lift between presses, and
saves every frame under a label matching the prompt, then prints the full
score table. Run it interactively in a terminal — do not drive presses from a
timer or a background process, which is how the superseded numbers above went
wrong.

## Building

Tested against libfprint master (1.94.x), Meson >= 1.0.

```sh
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cp egis0576.c egis0576.h egis_match.c libfprint/libfprint/drivers/

# register the driver (2 places):
# 1. top-level meson.build, in the drivers dict next to 'egis0570':
#        'egis0576': {},
# 2. libfprint/meson.build, in driver_sources next to egis0570:
#        'egis0576' : files('drivers/egis0576.c'),

cd libfprint
meson setup build -Ddrivers=egis0576 -Ddoc=false -Dintrospection=false -Dgtk-examples=false
ninja -C build
```

Note: if meson errors on `tests/meson.build` with "Foreach expects exactly 2
variables", change that `foreach driver_test:` loop to
`foreach driver_test, driver_test_info:` (upstream tree vs meson version skew).

Run without installing:

```sh
LD_LIBRARY_PATH=build/libfprint ./build/examples/enroll
LD_LIBRARY_PATH=build/libfprint ./build/examples/verify
```

`fprint-list-supported-devices` should show
`1c7a:0576 | Egis Technology Inc. EH576`.

## Offline matcher evaluation

`egis_match.c` builds standalone for evaluation against captured raw frames:

```sh
cc -O2 -DEGIS_MATCH_MAIN egis_match.c -o egis_match -lm
./egis_match a.bin b.bin        # match two 3990-byte raw frames
./egis_match dataset            # full eval over dataset/f{1..5}_{00..07}.bin
```

On a 5-finger x 8-press dataset this reproduces the Python prototype exactly:
pairwise d-prime 1.14; multi-template (5 enrolled) 13.3% FRR / 11.7% FAR at
the best operating point.

## Hardware warnings

- **Never USB-reset this sensor** (`dev.reset()`, `usbreset`): the firmware
  hangs and the device drops off the bus until a full *power-off* (not
  reboot).
- A second image request without a fresh REPEAT/arm sequence returns a blank
  frame — treat an all-zero frame as an invalid capture, never as "no finger".
