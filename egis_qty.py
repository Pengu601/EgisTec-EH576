"""Port of the vendor driver's `qty` metric -- the fingerprint quality score.

Reversed from rva 0x17038 and its block-map builder rva 0x15f6c (a 2.2 KB
routine) plus the consistency filter rva 0x15de8. This is the most informative
of the driver's four detect metrics (qty/corner/cover/level); its per-block
coherence and orientation maps are directly useful for matching, not just for
finger presence.

What qty measures:

  1. Sobel gradients Gx, Gy per pixel (rva 0x162de; centre weight 4).
  2. Per 16x16 block, the structure tensor:
        Gxx = sum(Gx*Gx)   Gyy = sum(Gy*Gy)   Gxy = sum(Gx*Gy)
  3. A 3-tap windowed sum of the tensor across neighbouring blocks.
  4. Orientation  = atan2(2*Gxy, Gxx-Gyy)/2  via the atan table at rva 0x393d0
     (verified: 45 deg == 240 units, fits to < 1 LSB). This orientation map is
     what the consistency filter 0x15de8 uses.
  5. Coherence    = sqrt((Gxx-Gyy)^2 + (2*Gxy)^2) / (Gxx+Gyy) via an integer
     sqrt table (rva 0x39000). This is the classic structure-tensor coherence,
     0..1, and is the per-block quality.
  6. A block is marked weak when at most half its neighbours are strong
     (rva 0x15de8), which drops isolated speckle.
  7. qty = 256 - weak*256/total. All-weak (no ridges) is 0; all-strong (clean
     print) is 256.

Validated end-to-end on labelled captures (Yoga 7 16IRL8, 1c7a:0576):
    no finger -> qty 0     finger -> qty 256
clean at both default and raised gain, stable across coherence thresholds
from 120 to 170.

Fidelity note: the structure-tensor math, the atan table, the coherence formula
and the final assembly are taken directly from the disassembly. The exact Sobel
tap offsets in 0x162de use block-row pointer arithmetic that was not reproduced
byte-for-byte; a standard 3x3 Sobel is used instead. Orientation and coherence
are robust to the exact kernel, so this shifts the qty scalar slightly, not its
behaviour. The intermediate maps cannot be checked against hardware because the
driver does not expose them.

Depends only on enhance.py (the vendor preprocessing chain). Stdlib otherwise.
"""
import math

import enhance as EN

FRAME_W, FRAME_H = 70, 57
FRAME_SIZE = FRAME_W * FRAME_H          # 3990
BLOCK = 16


def _sobel(img, w, h):
    """Standard 3x3 Sobel. Returns (gx, gy) as lists of int."""
    gx = [0] * (w * h)
    gy = [0] * (w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            tl, t, tr = img[i - w - 1], img[i - w], img[i - w + 1]
            l, r = img[i - 1], img[i + 1]
            bl, b, br = img[i + w - 1], img[i + w], img[i + w + 1]
            gx[i] = (tr + 2 * r + br) - (tl + 2 * l + bl)
            gy[i] = (bl + 2 * b + br) - (tl + 2 * t + tr)
    return gx, gy


def _isqrt_lut(v):
    """rva 0x39000 family -- piecewise integer sqrt, quantised per segment.
    Verified to reproduce every table entry over 0..0x7fff, so the 576 bytes of
    tables need not be shipped."""
    if v < 0x100:
        q = v
    elif v < 0x400:
        q = (v >> 4) << 4
    elif v < 0x1000:
        q = (v >> 5) << 5
    elif v < 0x4000:
        q = (v >> 6) << 6
    else:
        q = (v >> 7) << 7
    return int(math.sqrt(q) + 0.5)


def block_tensor(img, w=FRAME_W, h=FRAME_H):
    """Per-block (Gxx, Gyy, Gxy). Returns (grid, bw, bh)."""
    gx, gy = _sobel(img, w, h)
    bw, bh = w // BLOCK, h // BLOCK
    grid = []
    for by in range(bh):
        row = []
        for bx in range(bw):
            gxx = gyy = gxy = 0
            for yy in range(by * BLOCK, by * BLOCK + BLOCK):
                base = yy * w
                for xx in range(bx * BLOCK, bx * BLOCK + BLOCK):
                    i = base + xx
                    gxx += gx[i] * gx[i]
                    gyy += gy[i] * gy[i]
                    gxy += gx[i] * gy[i]
            row.append((gxx, gyy, gxy))
        grid.append(row)
    return grid, bw, bh


def _window_sum(grid, bw, bh, bx, by):
    """3-tap windowed tensor sum over the neighbouring blocks (rva 0x1645b)."""
    sxx = syy = sxy = 0
    for ny in range(max(0, by - 1), min(bh, by + 2)):
        for nx in range(max(0, bx - 1), min(bw, bx + 2)):
            a, b, c = grid[ny][nx]
            sxx += a
            syy += b
            sxy += c
    return sxx, syy, sxy


def orientation(gxx, gyy, gxy):
    """0.5*atan2(2*Gxy, Gxx-Gyy), in the driver's units (45 deg == 240)."""
    return 0.5 * math.atan2(2 * gxy, gxx - gyy) * (240.0 / (math.pi / 4))


def coherence(gxx, gyy, gxy):
    """sqrt((Gxx-Gyy)^2 + (2*Gxy)^2) / (Gxx+Gyy), scaled 0..255 (rva 0x1667e)."""
    trace = gxx + gyy
    if trace <= 0:
        return 0
    num = _isqrt_lut((gxx - gyy) ** 2 + (2 * gxy) ** 2)
    den = _isqrt_lut(trace * trace) or 1
    return min(255, num * 255 // den)


def _weak_count(strong, bw, bh):
    """rva 0x15de8 -- number of blocks marked 0xff (weak/isolated): those with
    at most half their neighbours strong."""
    weak = 0
    for by in range(bh):
        for bx in range(bw):
            n = tot = 0
            for ny in range(max(0, by - 1), min(bh, by + 2)):
                for nx in range(max(0, bx - 1), min(bw, bx + 2)):
                    tot += 1
                    if strong[ny][nx]:
                        n += 1
            if n <= tot // 2:
                weak += 1
    return weak


def qty(img70x57, coh_threshold=110):
    """Full qty on a raw 70x57 frame. Returns 0..256; higher = more clean ridge.

    Preprocesses with the vendor chain (background subtraction) first, exactly
    as the driver does, then scores.
    """
    enh = EN.background_subtract(img70x57, FRAME_W, FRAME_H)
    grid, bw, bh = block_tensor(enh, FRAME_W, FRAME_H)

    strong = [[coherence(*_window_sum(grid, bw, bh, bx, by)) >= coh_threshold
               for bx in range(bw)] for by in range(bh)]

    total = bw * bh
    weak = _weak_count(strong, bw, bh)
    return 256 - weak * 256 // total


def orientation_map(img70x57):
    """Per-block orientation in degrees, useful for matching/enhancement."""
    enh = EN.background_subtract(img70x57, FRAME_W, FRAME_H)
    grid, bw, bh = block_tensor(enh, FRAME_W, FRAME_H)
    return [[orientation(*_window_sum(grid, bw, bh, bx, by)) * (45.0 / 240.0)
             for bx in range(bw)] for by in range(bh)]


if __name__ == "__main__":
    import statistics
    import sys

    if len(sys.argv) < 2:
        sys.exit(f"usage: {sys.argv[0]} <frame.bin> [frame.bin ...]")
    print(f"{'frame':<28} {'variance':>9} {'qty':>5}")
    for path in sys.argv[1:]:
        data = open(path, "rb").read()[:FRAME_SIZE]
        if len(data) < FRAME_SIZE:
            print(f"{path:<28} {'short':>9} {'-':>5}")
            continue
        print(f"{path:<28} {statistics.pvariance(data):9.2f} {qty(data):5d}")
