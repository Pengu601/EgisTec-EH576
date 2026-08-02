# libfprint driver for the EgisTec EH576 (1c7a:0576)

A working **libfprint driver** for the EH576, written in C against current
libfprint master and validated end-to-end on real hardware (Lenovo Yoga 7
16IRL8): device init, finger detection, capture, 8-stage enrollment, and
verification all function through the standard libfprint API
(`examples/enroll`, `examples/verify`).

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

On-device numbers (one unit, one user): genuine presses score 0.47-0.89,
different-angle impostor fingers 0.11-0.21, threshold 0.28.

## Known limitation (honest disclosure)

**A finger whose ridge angle coincides with the enrolled prints can false
accept** (observed: same hand's thumb scoring 0.34-0.70 against index
templates). On a patch this small, most ridges are near-parallel, so global
correlation partly measures ridge *orientation and spacing* rather than ridge
*identity*. Multi-template consensus, peak-to-sidelobe ratio, and local-tile
agreement were all tried and do **not** separate this case.

Treat this as convenience-grade matching for now. The most promising paths:
mosaic-stitching the enrolled frames into a larger template (possibly enough
to hand back to NBIS), or a real minutiae+orientation-field matcher.
Contributions welcome — the matcher is deliberately isolated in
`egis_match.c` behind a tiny interface (`em_frame_compute` / `em_match`).

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
