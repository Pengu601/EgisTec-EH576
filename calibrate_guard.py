#!/usr/bin/env python3
"""Measure the agreement numbers the ghost guard should actually use.

The guard compares two frames of the same press and rejects the capture if
they disagree. Its threshold has to come from measurement, not guesswork:
this captures, for one press, the settled gain-0 frame, a second gain-0
frame, and a gain-6 frame, then reports how much each pair agrees.

  same-gain pair   -> what a legitimate capture looks like
  cross-gain pair  -> whether gain-6 can be compared to gain-0 at all

Run it yourself and press when prompted:
    cd ~/ai-projects/egistec-eh576 && python3 calibrate_guard.py [n_presses]
"""
import statistics
import sys
import time

import numpy as np
import usb.core

from detect_mode_test import PID, VID, execute_cmd, run_init
from capture_frames import fetch_frame
import corr_match as CM

VAR_THRESHOLD = 12.0
SETTLE_FRAMES = 3
GAIN_HI = 6

BOLD, GREEN, YELLOW, RESET = "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def variance(f):
    return statistics.pvariance(list(f))


def set_gain(dev, g):
    execute_cmd(dev, f"454749536112{g:02x}", timeout=400)


def wait_lift(dev):
    while True:
        f = fetch_frame(dev)
        if f is not None and variance(f) < VAR_THRESHOLD:
            return
        time.sleep(0.05)


def settle(dev):
    best, best_var, miss = None, 0.0, 0
    while True:
        f = fetch_frame(dev)
        if f is None:
            continue
        v = variance(f)
        if v < VAR_THRESHOLD:
            if best is not None:
                return best
            time.sleep(0.05)
            continue
        if v > best_var:
            best, best_var, miss = f, v, 0
        else:
            miss += 1
        if miss >= SETTLE_FRAMES:
            return best


def stats(name, vals):
    if not vals:
        return
    print(f"  {name:28} min {min(vals):.3f}  mean {sum(vals)/len(vals):.3f}  "
          f"max {max(vals):.3f}")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("sensor not found")
    run_init(dev)
    set_gain(dev, 0)
    print(f"{GREEN}Sensor ready.{RESET} {n} presses; keep your finger DOWN "
          f"until told to lift.\n")

    same, cross, clip = [], [], []
    for k in range(n):
        print(f"{BOLD}Press {k+1}/{n} — press and HOLD your right index"
              f"{RESET}", flush=True)
        wait_lift(dev)
        a = settle(dev)                      # gain-0, settled
        b = fetch_frame(dev)                 # gain-0, immediately after
        set_gain(dev, GAIN_HI)
        c = fetch_frame(dev)                 # gain-6, same press
        set_gain(dev, 0)

        if a is None or b is None or c is None:
            print("   capture failed, skipping\n")
            continue
        s = CM.ncc_masked(a, b)
        x = CM.ncc_masked(a, c)
        arr = np.frombuffer(c, np.uint8)
        pct_clipped = float(((arr == 0) | (arr == 255)).mean()) * 100
        same.append(s)
        cross.append(x)
        clip.append(pct_clipped)
        print(f"   gain0 vs gain0: {s:.3f}   gain0 vs gain6: {x:.3f}   "
              f"gain6 clipped px: {pct_clipped:.1f}%")
        print(f"   {YELLOW}lift your finger{RESET}\n", flush=True)
        wait_lift(dev)

    print(f"\n{BOLD}RESULTS ({len(same)} presses){RESET}")
    stats("same-gain agreement", same)
    stats("cross-gain agreement", cross)
    stats("gain-6 clipped pixels %", clip)
    if same:
        print(f"\n  A same-gain guard threshold of about "
              f"{max(0.0, min(same) - 0.15):.2f} would pass every one of these "
              f"presses.")
    if cross and max(cross) < 0.45:
        print(f"  {YELLOW}Cross-gain agreement never reaches 0.45 -> the "
              f"current guard rejects every gain-6 frame.{RESET}")


if __name__ == "__main__":
    main()
