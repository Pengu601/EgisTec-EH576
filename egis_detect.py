"""Finger detection ported from the EgisTec Windows driver.

The vendor's UMDF driver (EgisTouchFP0576.dll, from the Microsoft Update
Catalog) has no hardware finger-detect interrupt. Its `finger_detect` routine
captures one 70x57 frame and scores it in software, exactly the category of
solution this project already uses, and logs:

    [IsFP]detect qty = %d,corner = %d,cover = %d,level = %d

This module ports `level`, which is the metric that works best on real
captures. Every routine carries the rva it was reversed from so it can be
checked against the binary (version 3.10.3.5).

Why this beats a plain variance threshold: the core is a ridge detector that
only scores a window when its darkest and brightest samples sit 2 to 5 apart.
It responds to the *periodicity* of fingerprint ridges rather than to contrast
alone, so smudges, grease and slow baseline drift produce no score. The
thresholds are also derived per-frame via Otsu rather than hardcoded, so the
metric self-calibrates instead of needing a tuned cutoff.

Measured on 10 captures (Lenovo Yoga 7 16IRL8, sensor 1c7a:0576):

    no finger  variance 4.23 to 4.33   ->  level 0  (all 4 frames)
    finger     variance 16.1 to 18.9   ->  level 12 (all 6 frames)

Stdlib only. No numpy dependency.
"""
import math

FRAME_W, FRAME_H = 70, 57
FRAME_SIZE = FRAME_W * FRAME_H          # 3990

# The driver floors the ridge threshold at 18 (rva 0x15b0b). That constant is
# only right for one sensor gain, so prefer calibrate_floor() over any of these.
#
# Sensor gain lives in register 0x12 (0..15) and offset in register 0x0f
# (0..63), found in et5xx_fetch_dynamic_intensity (rva 0x8f90), where the
# driver runs a closed loop: drop the gain when a frame's max saturates at
# 0xff, raise it when the min bottoms out at 0. INIT_SEQUENCE leaves gain at
# 0, its minimum, which is why raw frames span only ~108..132.
#
# Raising the gain does NOT make the vendor's 18 correct. Measured across
# reg 0x12 = 0 and 6 (a ~13x change in noise), the usable floor tracks the
# sensor's own noise, not the constant:
#
#   reg 0x12 = 0   noise sd  2.06   floor  5   ->  no finger 0, finger 12
#   reg 0x12 = 6   noise sd 26.66   floor 67   ->  no finger 0, finger 9
#
# At gain 6 with floor 18, amplified noise clears the ridge test everywhere and
# every frame scores a saturated 12. Hence: derive the floor from a no-finger
# frame rather than hardcoding it.
VENDOR_RIDGE_FLOOR = 18
RIDGE_FLOOR = 5                 # correct for the default gain (reg 0x12 = 0)
FLOOR_NOISE_MULTIPLIER = 2.5

# level is 0..12; every no-finger frame measured 0 and every finger frame 12,
# so the midpoint is a safe cutoff.
LEVEL_THRESHOLD = 6


def otsu(buf, w, h, exclude_bright=0):
    """rva 0x5854 -- Otsu's threshold over a 256-bin histogram.

    Returns (threshold, mean_bright, mean_dark). With exclude_bright set,
    saturated pixels (>= 0xf0) are dropped from the histogram.

    The driver maximises sum0^2*w1/w0 + w0*sum1^2/w1 - 2*sum0*sum1, which is
    the standard between-class variance w0*w1*(mu0-mu1)^2 expanded out.
    """
    n = w * h
    hist = [0] * 256
    total = 0
    dropped = 0
    for i in range(n):
        v = buf[i]
        if exclude_bright > 0 and v >= 0xF0:
            dropped += 1
            continue
        total += v
        hist[v] += 1
    n -= dropped

    best_var = 0
    best_t = 0
    # seeded 0/1 the way the driver does, so the final divides are always safe
    b_sum0, b_w0, b_sum1, b_w1 = 0, 1, 0, 1
    w0 = 0
    sum0 = 0
    for t in range(256):
        if hist[t] == 0:
            continue
        w0 += hist[t]
        w1 = n - w0
        sum0 += hist[t] * t
        sum1 = total - sum0
        if w0 == 0 or w1 == 0:
            continue
        var = (sum0 * sum0 * w1) // w0 + (w0 * sum1 * sum1) // w1 - 2 * sum0 * sum1
        if var > best_var:
            best_var = var
            best_t = t
            b_sum0, b_w0, b_sum1, b_w1 = sum0, w0, sum1, w1
    return best_t, b_sum1 // b_w1, b_sum0 // b_w0


def otsu_contrast(buf, w, h):
    """rva 0x5804 -- mean_bright - mean_dark, as an 8-bit subtraction."""
    _, bright, dark = otsu(buf, w, h, exclude_bright=1)
    return (bright - dark) & 0xFF


def ridge_amplitude(buf, off, n=8, stride=1):
    """rva 0x15700 -- ridge detector over an n-sample window.

    Returns max-min, but only when the extrema sit 2..5 samples apart, which is
    the spacing a real fingerprint ridge produces at this resolution. Anything
    flatter or busier scores 0.
    """
    mn, mx = 255, 0
    mn_i, mx_i = 0, 0
    p = off
    for i in range(n):
        v = buf[p]
        if v < mn:
            mn, mn_i = v, i
        if v > mx:
            mx, mx_i = v, i
        p += stride
    if mx <= mn:
        return 0
    d = mx_i - mn_i
    if d < 0:
        d = -d
    if not (2 <= d <= 5):
        return 0
    return (mx - mn) & 0xFF


def _probe(buf, w, h, index, band, thresh, horizontal):
    """rva 0x1538c (rows) / rva 0x15280 (columns).

    Scans `band` parallel lines centred on `index`. A line counts if more than
    4 ridge features clear `thresh`; the probe passes if at least band//2 of its
    lines count.
    """
    half = (band - 1) // 2
    start, end = index - half, index + half
    if start < 0:
        return 0
    if end >= (h if horizontal else w):
        return 0

    limit = (w - 8) if horizontal else (h - 8)
    lines_ok = 0
    for line in range(start, end + 1):
        hits = 0
        pos = 2
        while pos < limit:
            if horizontal:
                off, stride = line * w + pos, 1
            else:
                off, stride = pos * w + line, w
            if ridge_amplitude(buf, off, 8, stride) > thresh:
                hits += 1
                pos += 9          # skip the rest of this ridge
            else:
                pos += 1
        if hits > 4:
            lines_ok += 1
    return 1 if lines_ok >= band // 2 else 0


def level(buf, w=FRAME_W, h=FRAME_H, band=5, floor=RIDGE_FLOOR):
    """rva 0x157a8 (reached via rva 0x1793c) -- 0..12 ridge-coverage score.

    Six probe lines (rows at 5, h/2, h-5; columns at w/4, w/2, 3w/4) are run at
    two thresholds derived from the frame's own Otsu contrast, giving 0..12.

    Operates on the raw 70x57 frame; the driver does not resample for this one.
    Pass floor=VENDOR_RIDGE_FLOOR to reproduce the driver bit-for-bit.
    """
    contrast = otsu_contrast(buf, w, h)
    t1 = floor if contrast == 0 else max(contrast >> 1, floor)
    t2 = ((3 * t1) // 2) & 0xFF     # the driver truncates this to a byte

    rows = (5, h // 2, h - 5)
    cols = (w // 4, w // 2, (3 * w) // 4)

    score = 0
    for thresh in (t1, t2):
        for r in rows:
            score += _probe(buf, w, h, r, band, thresh, True)
        for c in cols:
            score += _probe(buf, w, h, c, band, thresh, False)
    return score


def calibrate_floor(baseline_frame, k=FLOOR_NOISE_MULTIPLIER):
    """Derive the ridge floor from one no-finger frame.

    The ridge test has to sit above the sensor's noise, and that noise scales
    with whatever gain register 0x12 is set to. Taking the floor as k times the
    baseline standard deviation tracks it automatically: it reproduces the 5
    that was measured by hand at the default gain, and 67 at gain 6, both of
    which separate cleanly.

    Capture this once at startup with no finger on the sensor.
    """
    import statistics
    if len(baseline_frame) < FRAME_SIZE:
        return RIDGE_FLOOR
    sd = math.sqrt(statistics.pvariance(baseline_frame[:FRAME_SIZE]))
    return max(3, int(k * sd + 0.5))


def is_finger_present(image_bytes, threshold=LEVEL_THRESHOLD):
    """Drop-in replacement for the variance check."""
    if len(image_bytes) < FRAME_SIZE:
        return False
    return level(image_bytes) >= threshold


if __name__ == "__main__":
    import statistics
    import sys

    if len(sys.argv) < 2:
        sys.exit(f"usage: {sys.argv[0]} <frame.bin> [frame.bin ...]")
    print(f"{'frame':<28} {'variance':>9} {'level':>6}  verdict")
    for path in sys.argv[1:]:
        data = open(path, "rb").read()[:FRAME_SIZE]
        if len(data) < FRAME_SIZE:
            print(f"{path:<28} {'short':>9} {'-':>6}  skipped")
            continue
        lv = level(data)
        print(f"{path:<28} {statistics.pvariance(data):9.2f} {lv:6d}  "
              f"{'FINGER' if lv >= LEVEL_THRESHOLD else 'clear'}")
