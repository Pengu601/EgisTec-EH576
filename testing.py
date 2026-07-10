import usb.core
import usb.util
import time
import os
import sys
import statistics
import cv2
import numpy as np
from pathlib import Path

# ==========================================
# HARDWARE CONFIGURATION
# ==========================================
VID, PID = 0x1c7a, 0x0576
EP_OUT, EP_IN = 0x01, 0x82
IMG_SIZE = 3990 # 70x57 pixels

# Target directory for the raw .bin fingerprint dumps
TESTING_DIR = Path("testing_fingerprints")

# Sensor initialization sequence
INIT_SEQUENCE = [
    "45474953600000", "45474953600100", "454749536110fd", "45474953613502",
    "45474953618000", "45474953608000", "454749536110fc", "454749536301020f03",
    "45474953610c22", "45474953610983", "45474953632606066006052f06",
    "454749536110f4", "45474953610c44", "45474953615003", "45474953605000",
    "45474953640f96", # Flush Image Buffer
    "45474953604000", "4547495363090b832400440f082020000052",
    "45474953632606066006052f06", "45474953612300", "45474953612438",
    "45474953612000", "45474953612145", "45474953600000", "45474953600100",
    "45474953632c020057", "45474953602d00", "45474953626703",
    "45474953600f00", "45474953632c020013"
]

# Sequence used during polling to keep sensor active
REPEAT_SEQUENCE = [
    "45474953632c020057", "45474953602d00", "45474953626703",
    "45474953600f00", "45474953632c020013"
]

# ==========================================
# HARDWARE FUNCTIONS
# ==========================================
def log(msg):
    if not msg.startswith("\r"):
        print(f"[{time.strftime('%H:%M:%S.%f')[:-3]}] {msg}")

def execute_cmd(dev, hex_cmd, read_len=64, timeout=1000):
    try:
        dev.write(EP_OUT, bytes.fromhex(hex_cmd), timeout=timeout)
    except Exception:
        return b""
    time.sleep(0.01)
    try:
        return dev.read(EP_IN, read_len, timeout=timeout)
    except Exception:
        return b""

def is_finger_present(image_bytes):
    if len(image_bytes) < IMG_SIZE:
        return False
    try:
        variance = statistics.pvariance(image_bytes)
        return variance > 12.0
    except statistics.StatisticsError:
        return False

def setup_sensor():
    log("Initializing USB sensor...")
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        log("Sensor not found. Are you running as root/sudo?")
        sys.exit(1)

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass 

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    log("Claimed Egis sensor.")

    for cmd in INIT_SEQUENCE:
        expected_len = IMG_SIZE if cmd == "45474953640f96" else 64
        execute_cmd(dev, cmd, read_len=expected_len)
    
    log("Finished init sequence.")
    return dev

def _read_one_frame(dev):
    """Single raw frame pull -- no finger-presence check, just the raw read."""
    execute_cmd(dev, "45474953600000", timeout=500)
    dev.write(EP_OUT, bytes.fromhex("45474953640f96"), timeout=1000)

    image_buffer = bytearray()
    start_t = time.time()
    while time.time() - start_t < 0.5:
        try:
            chunk = dev.read(EP_IN, 4096, timeout=100)
            if chunk:
                image_buffer.extend(chunk)
                if len(image_buffer) >= IMG_SIZE:
                    break
        except usb.core.USBTimeoutError:
            break
    return bytes(image_buffer[:IMG_SIZE]) if len(image_buffer) >= IMG_SIZE else None


def capture_single_image(dev, n_avg=4):
    """Polls the sensor until a finger is detected, then grabs n_avg
    quick extra frames and averages them pixelwise before returning.
    This sensor is tiny and noisy -- a single raw frame carries a lot
    of read noise on top of the actual ridge signal, and averaging
    several frames while the finger is held still cuts that down
    without touching image size or DPI."""
    sys.stdout.write(f"\r[*] Awaiting capture... Place finger on sensor.")
    sys.stdout.flush()

    while True:
        for cmd in REPEAT_SEQUENCE:
            execute_cmd(dev, cmd)

        img_data = _read_one_frame(dev)

        if img_data and is_finger_present(img_data):
            variance = statistics.pvariance(img_data)
            log(f"\n[+] Finger detected (Variance: {variance:.2f})")

            frames = [np.frombuffer(img_data, dtype=np.uint8).reshape((70, 57)).astype(np.float32)]
            for _ in range(n_avg - 1):
                extra = _read_one_frame(dev)
                if extra:
                    frames.append(np.frombuffer(extra, dtype=np.uint8).reshape((70, 57)).astype(np.float32))

            averaged = np.mean(frames, axis=0)
            log(f"[i] Averaged {len(frames)} frames for this capture.")

            log("[-] Lift your finger.")
            time.sleep(1.5)
            return averaged.astype(np.uint8)

        time.sleep(0.05)

# ==========================================
# IMAGE PROCESSING & VERIFICATION
# ==========================================
_FLAT_FIELD = None


def load_flat_field(path: str = "flat_field.npy"):
    """Sensor fixed-pattern noise map, generated by capture_flat_field.py.
    Subtracting this removes noise that's identical across every finger,
    which was the main reason impostor scores were coming in at ~0.40
    instead of near 0."""
    global _FLAT_FIELD
    if _FLAT_FIELD is None and os.path.exists(path):
        _FLAT_FIELD = np.load(path)
        log(f"[i] Loaded flat-field correction from {path}")
    elif _FLAT_FIELD is None:
        log(f"[!] WARNING: {path} not found. Run capture_flat_field.py first "
            f"-- without it, sensor noise inflates every match score.")
    return _FLAT_FIELD


def estimate_orientation_field(img: np.ndarray, block_size: int = 8) -> np.ndarray:
    """Local ridge-flow direction per block (Rao's method) -- this is
    the piece that was missing. Max-over-orientations threw away flow
    direction, which is what actually differs between fingers."""
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)

    h, w = img.shape
    bh, bw = h // block_size, w // block_size
    orientation = np.zeros((bh, bw), dtype=np.float32)

    for i in range(bh):
        for j in range(bw):
            y0, y1 = i * block_size, (i + 1) * block_size
            x0, x1 = j * block_size, (j + 1) * block_size
            gx_b = gx[y0:y1, x0:x1]
            gy_b = gy[y0:y1, x0:x1]
            vx = np.sum(2 * gx_b * gy_b)
            vy = np.sum(gx_b ** 2 - gy_b ** 2)
            orientation[i, j] = 0.5 * np.arctan2(vx, vy)

    return orientation


def foreground_mask(img: np.ndarray, block_size: int = 8, energy_percentile: float = 40) -> np.ndarray:
    """Flags low-gradient-energy blocks as background/no-contact area
    so they stop dragging every score toward the same baseline."""
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
    energy = gx ** 2 + gy ** 2

    h, w = img.shape
    bh, bw = h // block_size, w // block_size
    block_energy = np.zeros((bh, bw), dtype=np.float32)

    for i in range(bh):
        for j in range(bw):
            y0, y1 = i * block_size, (i + 1) * block_size
            x0, x1 = j * block_size, (j + 1) * block_size
            block_energy[i, j] = energy[y0:y1, x0:x1].mean()

    thresh = np.percentile(block_energy, energy_percentile)
    return block_energy > thresh


def orientation_guided_enhance(img: np.ndarray, block_size: int = 8, lambd: float = 6.0) -> np.ndarray:
    """Filters each block with a Gabor kernel matched to that block's
    own ridge direction, preserving actual flow pattern instead of
    collapsing it into a generic ridge-density map."""
    orientation = estimate_orientation_field(img, block_size)
    h, w = img.shape
    bh, bw = h // block_size, w // block_size
    output = np.zeros_like(img, dtype=np.float32)
    ksize, sigma, gamma = 9, 3.0, 0.5

    for i in range(bh):
        for j in range(bw):
            theta = orientation[i, j]
            kernel = cv2.getGaborKernel((ksize, ksize), sigma, theta, lambd, gamma, 0, ktype=cv2.CV_32F)
            filtered = cv2.filter2D(img, cv2.CV_32F, kernel)
            y0, y1 = i * block_size, (i + 1) * block_size
            x0, x1 = j * block_size, (j + 1) * block_size
            output[y0:y1, x0:x1] = filtered[y0:y1, x0:x1]

    return output


def preprocess(img: np.ndarray):
    """Returns (enhanced_image, foreground_mask)."""
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    img = img.astype(np.float32)

    flat = load_flat_field()
    if flat is not None:
        img = img - flat
        img = img - img.min()

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    img_u8 = np.clip(img, 0, 255).astype(np.uint8)
    img_eq = clahe.apply(img_u8)

    mask = foreground_mask(img_eq.astype(np.float32))
    img_ridge = orientation_guided_enhance(img_eq.astype(np.float32))
    img_blur = cv2.GaussianBlur(img_ridge, (3, 3), 0)

    img_norm = (img_blur - img_blur.mean()) / (img_blur.std() + 1e-6)
    return img_norm, mask

def align_translation(probe: np.ndarray, template: np.ndarray) -> np.ndarray:
    shift, _ = cv2.phaseCorrelate(template, probe)
    dx, dy = shift
    h, w = probe.shape
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    aligned = cv2.warpAffine(probe, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return aligned

def block_match_score(probe: np.ndarray, probe_mask: np.ndarray,
                       template: np.ndarray, template_mask: np.ndarray,
                       block_size: int = 8) -> float:
    """Median of per-block correlation, skipping background blocks --
    a mismatched region actually pulls the score down instead of
    getting smoothed away by a single global number."""
    h, w = probe.shape
    bh, bw = h // block_size, w // block_size
    scores = []

    for i in range(bh):
        for j in range(bw):
            if not (probe_mask[i, j] and template_mask[i, j]):
                continue
            y0, y1 = i * block_size, (i + 1) * block_size
            x0, x1 = j * block_size, (j + 1) * block_size
            p_block = probe[y0:y1, x0:x1]
            t_block = template[y0:y1, x0:x1]
            if p_block.std() < 1e-3 or t_block.std() < 1e-3:
                continue
            result = cv2.matchTemplate(p_block, t_block, cv2.TM_CCOEFF_NORMED)
            scores.append(float(result.max()))

    if not scores:
        return -1.0

    return float(np.median(scores))

def best_rotation_score(probe: np.ndarray, probe_mask: np.ndarray,
                         template: np.ndarray, template_mask: np.ndarray,
                         angle_range=8, angle_step=2) -> float:
    h, w = probe.shape
    center = (w / 2, h / 2)
    best = -1.0

    for angle in range(-angle_range, angle_range + 1, angle_step):
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(probe, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
        aligned = align_translation(rotated, template)
        score = block_match_score(aligned, probe_mask, template, template_mask)
        best = max(best, score)

    return best

def verify(probe_image: np.ndarray, threshold: float = 0.50, debug: bool = True) -> tuple[bool, float]:
    if not TESTING_DIR.exists():
        raise FileNotFoundError(f"Directory '{TESTING_DIR}' does not exist.")

    template_files = list(TESTING_DIR.glob("left_index_0*.bin"))
    
    if not template_files:
        raise FileNotFoundError(f"No left_index_0XX.bin files found in {TESTING_DIR}/")

    print(f"[*] Found {len(template_files)} stored templates to test against...")
    probe, probe_mask = preprocess(probe_image)
    best_score = -1.0
    per_template = []

    for bin_path in template_files:
        with open(bin_path, "rb") as f:
            raw_data = f.read()

        if len(raw_data) < IMG_SIZE:
            continue

        template_img = np.frombuffer(raw_data[:IMG_SIZE], dtype=np.uint8).reshape((70, 57))
        template, template_mask = preprocess(template_img)
        
        score = best_rotation_score(probe, probe_mask, template, template_mask)
        per_template.append((bin_path.name, score))
        best_score = max(best_score, score)

    if debug:
        for name, score in sorted(per_template, key=lambda x: -x[1]):
            print(f"    {name}: {score:.3f}")

    accepted = best_score >= threshold
    return accepted, best_score

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    if not TESTING_DIR.exists():
        print(f"[!] Warning: The directory '{TESTING_DIR}' does not exist.")
        print(f"    Please create it and add your 'left_index_0XX.bin' files before verifying.")
        sys.exit(1)
        
    dev = setup_sensor()

    try:
        while True:
            print("\n" + "="*40)
            print("Ready for live verification.")
            print("Press ENTER to scan, or type 'q' to quit.")
            choice = input("> ").strip().lower()

            if choice == 'q':
                break
                
            probe = capture_single_image(dev)
            
            try:
                accepted, score = verify(probe)
                if accepted:
                    print(f"\n>>> ✅ ACCEPTED! (Highest Match Score: {score:.3f}) <<<")
                else:
                    print(f"\n>>> ❌ REJECTED! (Highest Match Score: {score:.3f}) <<<")
            except FileNotFoundError as e:
                print(f"\n[!] Error: {e}")
                
    except KeyboardInterrupt:
        log("Process aborted by user.")
    finally:
        usb.util.release_interface(dev, 0)
        log("Released Egis sensor.")