#!/usr/bin/env python3
"""Interactive matcher-evaluation harness with explicit prompts.

Run this YOURSELF in a terminal (not via a background timer):

    cd ~/ai-projects/egistec-eh576 && python3 test_matching.py

It guides you through labeled phases (enroll / genuine probes / impostor
probes), shows a big banner before every press saying exactly which finger
to use, gives instant feedback per press (captured/rejected + coverage),
and only advances when a press is accepted. Every frame is saved with its
label under session_<timestamp>/ so the dataset's ground truth is exactly
what you did, not what a timer guessed.

Capture mirrors the libfprint driver: detect at gain 0 (variance > 12),
wait for the press to settle (peak variance), then take the match frame at
gain 6 (with the mandatory re-arm), restore gain 0, and require a finger
lift before the next press.
"""
import os
import sys
import time
import statistics
from datetime import datetime

import usb.core

from detect_mode_test import (EP_IN, EP_OUT, IMG_SIZE, PID, VID,
                              execute_cmd, run_init)
from capture_frames import fetch_frame
import corr_match as CM

VAR_THRESHOLD = 12.0
SETTLE_FRAMES = 3
PRESS_FRAMES_MAX = 20
MIN_COVERAGE = 0.55
MATCH_THRESHOLD = 0.53
GHOST_THRESHOLD = 0.45   # gain-6 frame must agree with its gain-0 settle frame
GAIN_HI = 6

# Enrolment must cover *different parts of the fingertip*, not the same spot
# eight times: a probe only matches if it lands on enrolled territory, so
# coverage is what drives the false-reject rate. Same idea as the "adjust
# your grip" phase of phone fingerprint enrolment.
ENROLL_POSITIONS = [
    "flat and centered — your normal unlock press",
    "slide your finger UP, so the sensor sees nearer the TIP",
    "slide your finger DOWN, so the sensor sees nearer the KNUCKLE",
    "shift LEFT — sensor toward the left edge of your fingerprint",
    "shift RIGHT — sensor toward the right edge",
    "ROLL your finger onto its LEFT side",
    "ROLL your finger onto its RIGHT side",
    "flat and centered again, slightly different angle",
]

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def variance(frame):
    vals = list(frame)
    return statistics.pvariance(vals)


def set_gain(dev, gain):
    execute_cmd(dev, f"454749536112{gain:02x}", timeout=400)


def wait_for_lift(dev):
    while True:
        f = fetch_frame(dev)
        if f is not None and variance(f) < VAR_THRESHOLD:
            return
        time.sleep(0.05)


def capture_press(dev):
    """Wait for a fresh press, settle, return the gain-6 match frame."""
    # require a clear sensor first so we never reuse a lingering press
    wait_for_lift(dev)
    best, best_var, misses, frames = None, 0.0, 0, 0
    while True:
        f = fetch_frame(dev)
        if f is None:
            time.sleep(0.05)
            continue
        v = variance(f)
        if v < VAR_THRESHOLD:
            if best is not None:
                break            # lifted mid-settle: use what we have
            time.sleep(0.05)
            continue
        frames += 1
        if v > best_var:
            best, best_var, misses = f, v, 0
        else:
            misses += 1
        if misses >= SETTLE_FRAMES or frames >= PRESS_FRAMES_MAX:
            break
    # High-quality frame at gain 6 (fetch_frame re-arms internally).
    # The sensor sometimes serves a ghost of an earlier press, so require the
    # gain-6 frame to agree with the gain-0 frame we just settled on.
    for _ in range(3):
        set_gain(dev, GAIN_HI)
        hq = fetch_frame(dev)
        set_gain(dev, 0)
        if hq is None:
            continue
        agree = CM.ncc_masked(hq, best)
        if agree >= GHOST_THRESHOLD:
            return hq
        print(f"    {YELLOW}stale frame discarded{RESET} (agreement {agree:.2f}) — retaking")
    return best


def prompt_press(dev, k, n, finger, hint):
    while True:
        print(f"\n{BOLD}{CYAN}=== Press {k}/{n} — {finger.upper()} ==={RESET}")
        print(f"    ({hint})")
        print("    ... waiting for your press ...", flush=True)
        frame = capture_press(dev)
        cov = CM.coverage(frame)
        if cov >= MIN_COVERAGE:
            print(f"    {GREEN}CAPTURED{RESET}  coverage {cov:.2f}")
            print("    Lift your finger.", flush=True)
            wait_for_lift(dev)
            return frame
        print(f"    {RED}REJECTED{RESET}  coverage {cov:.2f} — partial/light press."
              f" Lift and press again, flatter and firmer.")
        wait_for_lift(dev)


def run_phase(dev, outdir, tag, finger, count, hint, positions=None):
    print(f"\n{BOLD}{'='*62}\nPHASE: {tag.upper()} — {count} presses with your"
          f" {finger.upper()}\n{'='*62}{RESET}")
    input(f"Have your {BOLD}{finger.upper()}{RESET} ready, then hit ENTER to start...")
    frames = []
    for k in range(count):
        this_hint = positions[k] if positions else hint
        f = prompt_press(dev, k + 1, count, finger, this_hint)
        path = os.path.join(outdir, f"{tag}_{k:02d}.bin")
        with open(path, "wb") as fh:
            fh.write(f)
        frames.append(f)
    print(f"{GREEN}{tag}: {count}/{count} captured.{RESET}")
    return frames


def score_probes(enrolled, probes):
    out = []
    for p in probes:
        out.append(max(CM.ncc_masked(p, e) for e in enrolled))
    return out


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("sensor not found")
    run_init(dev)
    print(f"{GREEN}Sensor initialised.{RESET}")

    outdir = f"session_{datetime.now():%Y%m%d_%H%M%S}"
    os.makedirs(outdir, exist_ok=True)
    print(f"Frames will be saved to {outdir}/ (local only — biometric data).")

    print(f"\n{YELLOW}Enrolment covers different parts of the fingertip — follow\n"
          f"the position for each press; that coverage is what makes later\n"
          f"verification succeed.{RESET}")
    enrolled = run_phase(dev, outdir, "enroll", "right index",
                         len(ENROLL_POSITIONS), "", positions=ENROLL_POSITIONS)
    genuine = run_phase(dev, outdir, "genuine", "right index", 5,
                        "natural placement, as you would to unlock")
    impostor_t = run_phase(dev, outdir, "impostor-thumb", "right thumb", 5,
                           "natural placement")
    extra = input("\nAlso test LEFT INDEX as a second impostor? [y/N] ").strip().lower()
    impostor_l = []
    if extra == "y":
        impostor_l = run_phase(dev, outdir, "impostor-leftindex", "left index", 5,
                               "natural placement")

    print(f"\n{BOLD}Scoring (best-of-8 masked NCC, threshold {MATCH_THRESHOLD})...{RESET}")
    g = score_probes(enrolled, genuine)
    it = score_probes(enrolled, impostor_t)
    il = score_probes(enrolled, impostor_l) if impostor_l else []

    def show(name, scores, should_match):
        print(f"\n  {BOLD}{name}{RESET}")
        ok = 0
        for s in scores:
            matched = s >= MATCH_THRESHOLD
            good = matched == should_match
            ok += good
            mark = GREEN + "✓" + RESET if good else RED + "✗" + RESET
            print(f"    score {s:.3f}  ->  {'MATCH' if matched else 'no match'}  {mark}")
        print(f"    correct: {ok}/{len(scores)}")

    show("genuine (right index) — should MATCH", g, True)
    show("impostor (right thumb) — should NOT match", it, False)
    if il:
        show("impostor (left index) — should NOT match", il, False)

    gap = min(g) - max(it + il) if g and (it or il) else float("nan")
    print(f"\n  {BOLD}worst-case margin (min genuine − max impostor): {gap:+.3f}{RESET}")
    if gap > 0:
        print(f"  {GREEN}SEPARABLE: a threshold between "
              f"{max(it + il):.3f} and {min(g):.3f} classifies everything correctly.{RESET}")
    else:
        print(f"  {RED}NOT separable by best-score threshold on this run.{RESET}")
    print(f"\nAll frames labeled in {outdir}/ for offline analysis.")


if __name__ == "__main__":
    main()
