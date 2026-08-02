# libfprint driver for the EgisTec EH576 (1c7a:0576)

A **libfprint driver** for the EH576, written in C against current libfprint
master and validated end-to-end on real hardware (Lenovo Yoga 7 16IRL8):
device init, finger detection, capture, 8-stage enrollment, and verification
all run through the standard libfprint API (`examples/enroll`,
`examples/verify`).

**Status: working, including matching.** Over two labelled test sessions
(coverage-guided enrolment; 10 genuine and 16 impostor probes from two other
fingers) the matcher accepts no impostor press and rejects 10% of genuine
presses at its operating threshold — see "Measured performance" below, along
with an honest account of how small that sample is.

Two things were needed to get there, and both are worth reading if you are
building on this sensor: enrolment has to **cover different parts of the
fingertip**, and the sensor intermittently **serves a stale frame** that must
be detected and discarded (see "Ghost frames" — it silently produced false
accepts before we caught it).

The protocol layer is built directly on this project's findings (INIT/REPEAT
sequences, variance-based finger detection, the gain register) plus the vendor
preprocessing reverse-engineered from the Windows driver.

## Files

| File | Contents |
|---|---|
| `egis0576.c` | The driver: USB protocol, init/capture state machines, enrollment, identification |
| `egis0576.h` | Init/repeat packet tables and device constants |
| `egis_match.c` | Correlation matcher; also builds standalone as an offline eval tool |
| `egis_match.h` | Matcher interface (`em_frame_compute` / `em_match`) — replace the matcher without touching the USB or state-machine code |

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
- **Everything runs at the default gain.** An earlier revision re-captured
  the matching frame at gain 6 (register 0x12) for ~2.4x ridge SNR. Measured
  on hardware, a gain-6 frame and the gain-0 frame of the same press agree at
  **0.99** once enhanced and masked, so the extra gain gives the matcher
  nothing, while clipping 12-23% of pixels to black and adding ~300ms per
  capture. (If you do use a gain change: the sensor must be re-armed with the
  REPEAT sequence between the register write and the image request, or it
  returns a blank frame.)
- **Enrollment** collects 8 coverage-gated presses (coherence mask must cover
  >= 55% of the frame) and stores the raw frames in the print's `fpi-data`.
- **Verification** enhances the probe (3x3 box mean minus 9x9 box mean — the
  vendor's own background subtraction, kills fixed-pattern noise with no
  stored calibration), masks to coherent-ridge blocks (structure-tensor
  coherence, from the vendor's `qty` metric), and scores translation-searched
  normalized cross-correlation against each enrolled frame, best-of-8.
- **Every matching frame is checked against its own detect frame** to reject
  stale "ghost" frames (see below).

## Measured performance

Every press below was explicitly prompted and labelled at press time (see
"Evaluation harness"), and every dataset was scanned for ghost frames before
scoring. Two sessions, each with 8 coverage-guided enrolment templates for a
right index finger, then genuine probes plus impostor probes from a right
thumb and a left index finger, scored best-of-8:

| | scores |
|---|---|
| genuine (10 probes) | 0.421, 0.574, 0.672, 0.691, 0.704, 0.712, 0.803, 0.837, 0.849, 0.923 |
| impostor (16 probes) | 0.244 … 0.528 (max) |

At the shipped threshold of **0.53: 0% false accept, 10% false reject.** The
single false reject is the 0.421 press, which landed away from the enrolled
area; a retry fixes it. One of the two sessions separates completely (every
genuine above every impostor).

**How small this sample is:** one sensor, one person, 26 probes, two impostor
fingers. That is enough to show the driver works and nowhere near enough to
quote a FAR/FRR spec. The margin is also thin — the worst genuine press
(0.421) sits below the best impostor (0.528), and only the coverage of
enrolment keeps genuine presses in the 0.6-0.9 band. Independent data from
other units and other fingers is very welcome.

### Coverage is what drives the false-reject rate

Correlation on a patch this small separates **decisively when the probe
overlaps an enrolled region** (0.6-0.9) and **not at all when it doesn't**
(0.35-0.45, indistinguishable from an impostor). So the fix for false
rejects is not a cleverer score, it is enrolling more of the fingertip.

Enrolling eight presses at the same comfortable position covers about twice
one frame's area and gave a 60% false-reject rate. Prompting for eight
*distinct* positions — centred, toward the tip, toward the knuckle, left,
right, rolled left, rolled right — dropped that to 10% with no loss of
security. This is the same "adjust your grip" phase phone sensors use, and
on a sensor this small it is not optional.

An earlier revision of this file reported that genuine and impostor scores
overlapped and concluded that correlation could not carry identity. That was
wrong twice over: the threshold was far too low (0.28, which accepts 80% of
impostor presses), and the datasets contained ghost frames (below) that
manufactured both a phantom "genuine" match and two phantom false accepts.

## Ghost frames — a silent false-accept vector

**This sensor intermittently returns a stale frame: a ghost of an earlier
press, carrying fresh sensor noise.** Because the noise differs, the frame is
not byte-identical to the original and checksums will not catch it. Against
the earlier print it correlates ~0.98.

How it showed up: in two separate datasets, a frame captured while a
completely different finger was on the sensor turned out to correlate 0.98
with the *first* frame captured that session. In one dataset that produced a
fake "genuine" match; in another it produced two false accepts, scoring 0.974
where real impostor presses score below 0.53. Left undetected in a driver,
this is an authentication bypass: press any finger, occasionally get in.

The re-arm (REPEAT) sequence does **not** prevent it, so it is not simply a
stale USB buffer; it looks like frame retention on the sensor side, in the
same family as this sensor's other known latching behaviour.

**The guard used here:** the frame selected for matching must agree with
another frame captured from the same press, at the same gain. Two frames of
one held press agree at **0.997-0.998** (measured over five presses), so the
threshold sits at 0.85 — wide margin for a normal press, while a ghost of a
different press shows a different finger in a different position and falls
far below it. A press that fails the check is discarded entirely and the
driver waits for a fresh one. See `accept_press()` in `egis0576.c`.

**A cautionary note on how this guard was first written**, since it is an
easy trap: the original version compared the gain-0 detect frame against a
gain-6 match frame with a threshold picked by guesswork. On hardware it
rejected *every* frame (agreement 0.115-0.216) and silently fell back, so the
guard protected nothing while appearing to be present. The cause was latency,
not gain — the second capture landed ~500ms after the first, by which time a
quick press was over and the sensor was imaging nothing. **Calibrate a guard
threshold against measured same-press agreement before trusting it**;
`calibrate_guard.py` in the repo root does exactly that, and prints what a
legitimate capture actually looks like.

**If you collect data from this sensor, scan for ghosts before trusting it:**
compare every pair of frames carrying *different* labels and flag any raw
correlation above 0.95. Two presses of genuinely different fingers cannot do
that. `test_matching.py` captures labelled data suitable for exactly this
check.

## Evaluation harness

Trustworthy numbers need labeled presses. `test_matching.py` in the repo root
prompts for each press by name ("Press 3/8 — RIGHT INDEX"), waits for you,
reports captured/rejected with coverage, forces a lift between presses, and
saves every frame under a label matching the prompt, then prints the full
score table, and discards ghost frames as it goes. It prompts a distinct
finger position for each enrolment press, which is what keeps the false-reject
rate down. Run it interactively in a terminal — do not drive presses from a
timer or a background process, which is how the superseded numbers above went
wrong.

## Building

Tested against libfprint master (1.94.x), Meson >= 1.0.

The quickest route is `install.sh` in the repo root, which does all of the
below (and `./install.sh --uninstall` reverses it). Manually:

```sh
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cp egis0576.c egis0576.h egis_match.c egis_match.h libfprint/libfprint/drivers/

# register the driver (2 places):
# 1. top-level meson.build, in the drivers dict next to 'egis0570':
#        'egis0576': {},
# 2. libfprint/meson.build, in driver_sources next to egis0570:
#        'egis0576' : files(
#            'drivers/egis0576.c',
#            'drivers/egis_match.c',
#        ),

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

## Using it for login (fprintd + PAM)

Verified on Linux Mint 22.2 with the distribution's fprintd 1.94.3 and
libpam-fprintd, against this driver built from libfprint master. The build
here is ABI-compatible with the packaged fprintd: check with
`nm -D --undefined-only /usr/libexec/fprintd` against the exported symbols of
the built library (strip the `@VERSION` suffixes before comparing, or every
symbol looks missing).

Install to `/usr/local`, which precedes `/usr/lib` in the linker search path,
so fprintd picks up this build without touching any packaged file:

```sh
meson setup build --prefix=/usr/local --libdir=lib/x86_64-linux-gnu \
    -Ddrivers=egis0576 -Ddoc=false -Dintrospection=false -Dgtk-examples=false
ninja -C build
sudo meson install -C build
sudo ldconfig
ldd /usr/libexec/fprintd | grep libfprint      # must show /usr/local/...
```

To undo completely:
`sudo rm -f /usr/local/lib/x86_64-linux-gnu/libfprint-2.so* && sudo ldconfig`

Then enroll and test. fprintd is D-Bus activated, so stopping it is enough to
make the next command pick up a newly installed library:

```sh
sudo systemctl stop fprintd
fprintd-enroll        # vary finger position across the 8 presses -- see below
fprintd-verify
```

**`fprintd-enroll` gives no positional guidance**, so move your finger
deliberately between presses (centred, toward the tip, toward the knuckle,
left, right, rolled left, rolled right, centred). Enrolling eight presses at
one position is the difference between a 10% and a 60% false-reject rate.

For login and `sudo`, enable the PAM profile:

```sh
sudo pam-auth-update --enable fprintd
```

That places `pam_fprintd` ahead of `pam_unix` with `success=end`, leaving the
password path intact as a fallback — which matters, because a press that
lands off the enrolled area is rejected and you will want to type a password
rather than fight the sensor. Keep a root shell open while you test, and
verify with `sudo -k && sudo true` in a fresh terminal before logging out.

Lock-screen unlock works through the same PAM stack with no extra
configuration.

## Hardware warnings

- **Never USB-reset this sensor** (`dev.reset()`, `usbreset`): the firmware
  hangs and the device drops off the bus until a full *power-off* (not
  reboot).
- A second image request without a fresh REPEAT/arm sequence returns a blank
  frame — treat an all-zero frame as an invalid capture, never as "no finger".
