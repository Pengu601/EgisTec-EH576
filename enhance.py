"""Port of the vendor driver's image preprocessing chain.

From the `qty` path in rva 0x17038, which runs three passes before scoring:

    rva 0x16c20   box_mean(radius 1)   -- 3x3 mean, light denoise
    rva 0x16db8   box_mean(radius 4)   -- 9x9 mean, background estimate
    rva 0x16824   rolling sum of |A - B| over a large window -- local energy

All three use rolling accumulators and normalise by the actual number of
pixels in the window, so edges are handled correctly rather than clamped.

The middle pass is the interesting one: subtracting a heavily blurred copy is
background subtraction, which removes exactly the fixed-pattern non-uniformity
that makes this sensor's raw frames so uneven (measured at 79% of a clear
frame's spatial contrast at default gain, 85% at gain 6).
"""
import statistics


def box_mean(img, w, h, radius):
    """rva 0x16c20 (radius 1) / rva 0x16db8 (radius 4).

    Separable box mean over a (2r+1) square, normalised by the true count of
    contributing pixels so border pixels are not darkened.
    """
    # vertical pass into per-column sums, then horizontal
    out = bytearray(w * h)
    for y in range(h):
        y0, y1 = max(0, y - radius), min(h - 1, y + radius)
        col = [0] * w
        for yy in range(y0, y1 + 1):
            base = yy * w
            for x in range(w):
                col[x] += img[base + x]
        rows_n = y1 - y0 + 1
        run = 0
        for x in range(w):
            x0, x1 = max(0, x - radius), min(w - 1, x + radius)
            if x == 0:
                run = sum(col[x0:x1 + 1])
            else:
                if x - radius - 1 >= 0:
                    run -= col[x - radius - 1]
                if x + radius < w:
                    run += col[x + radius]
            n = (x1 - x0 + 1) * rows_n
            out[y * w + x] = min(255, run // n)
    return out


def background_subtract(img, w, h, light=1, heavy=4, offset=128):
    """A = box_mean(img, light); B = box_mean(A, heavy); return A - B + offset.

    This is the driver's A/B pair expressed as a high-pass filter. The result
    is centred on `offset` with the slowly-varying background removed.
    """
    a = box_mean(img, w, h, light)
    b = box_mean(a, w, h, heavy)
    return bytes(min(255, max(0, a[i] - b[i] + offset)) for i in range(w * h))


def local_energy(a, b, w, h, radius=4):
    """rva 0x16824 -- mean |A - B| over a window, as a per-pixel map.

    The driver runs this with radius 0x40, which exceeds the image height, so
    the window spans the whole frame vertically. Kept configurable here.
    """
    out = bytearray(w * h)
    for y in range(h):
        y0, y1 = max(0, y - radius), min(h - 1, y + radius)
        for x in range(w):
            x0, x1 = max(0, x - radius), min(w - 1, x + radius)
            total = 0
            n = 0
            for yy in range(y0, y1 + 1):
                base = yy * w
                for xx in range(x0, x1 + 1):
                    total += abs(a[base + xx] - b[base + xx])
                    n += 1
            out[y * w + x] = min(255, total // n)
    return out


def ridge_snr(frames_clear, frame_finger, amp_fn):
    """Signal-to-noise using temporal noise, which is the honest measure.

    Spatial contrast of a clear frame is mostly fixed pattern, and counting
    that as noise gives the wrong answer -- it made background subtraction look
    useless when it is the thing that removes it.
    """
    n = len(frames_clear[0])
    sds = []
    for i in range(n):
        sds.append(statistics.pstdev([f[i] for f in frames_clear]))
    noise = sum(sds) / len(sds)
    return amp_fn(frame_finger) / max(noise, 1e-6), noise
