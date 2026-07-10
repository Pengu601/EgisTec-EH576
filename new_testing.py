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
IMG_SIZE = 3990 # Reshaped to 57x70 pixels

TEMPLATE_DIR = Path("testing_fingerprints")

INIT_SEQUENCE = [
    "45474953600000", "45474953600100", "454749536110fd", "45474953613502",
    "45474953618000", "45474953608000", "454749536110fc", "454749536301020f03",
    "45474953610c22", "45474953610983", "45474953632606066006052f06",
    "454749536110f4", "45474953610c44", "45474953615003", "45474953605000",
    "45474953640f96", "45474953604000", "4547495363090b832400440f082020000052",
    "45474953632606066006052f06", "45474953612300", "45474953612438",
    "45474953612000", "45474953612145", "45474953600000", "45474953600100",
    "45474953632c020057", "45474953602d00", "45474953626703",
    "45474953600f00", "45474953632c020013"
]

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

def capture_single_image(dev):
    sys.stdout.write(f"\r[*] Awaiting capture... Place finger on sensor.")
    sys.stdout.flush()
    while True:
        for cmd in REPEAT_SEQUENCE:
            execute_cmd(dev, cmd)
        
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
        
        if len(image_buffer) >= IMG_SIZE:
            img_data = image_buffer[:IMG_SIZE]
            if is_finger_present(img_data):
                log("\n[~] Initial touch detected. Waiting 250ms for finger to settle...")
                time.sleep(0.25) 
                
                for cmd in REPEAT_SEQUENCE:
                    execute_cmd(dev, cmd)
                    
                execute_cmd(dev, "45474953600000", timeout=500)
                dev.write(EP_OUT, bytes.fromhex("45474953640f96"), timeout=1000)
                
                settled_buffer = bytearray()
                start_t2 = time.time()
                while time.time() - start_t2 < 0.5:
                    try:
                        chunk = dev.read(EP_IN, 4096, timeout=100)
                        if chunk:
                            settled_buffer.extend(chunk)
                            if len(settled_buffer) >= IMG_SIZE:
                                break
                    except usb.core.USBTimeoutError:
                        break
                        
                if len(settled_buffer) >= IMG_SIZE:
                    settled_data = settled_buffer[:IMG_SIZE]
                    variance = statistics.pvariance(settled_data)
                    log(f"[+] Settled fingerprint captured (Variance: {variance:.2f})")
                    img_array = np.frombuffer(settled_data, dtype=np.uint8).reshape((57, 70))
                    
                    log("[-] Lift your finger.")
                    time.sleep(1.5) 
                    return img_array
        time.sleep(0.05) 

# ==========================================
# PREPROCESSING & SIFT MATCHING LOGIC
# ==========================================
def enhance_image(img: np.ndarray) -> np.ndarray:
    """
    Normalizes contrast, upscales by 4x for SIFT compatibility, 
    and applies CLAHE for ridge isolation.
    """
    img_float = img.astype(np.float32)
    min_val, max_val = np.min(img_float), np.max(img_float)
    
    if max_val > min_val:
        normalized = ((img_float - min_val) / (max_val - min_val) * 255.0)
    else:
        normalized = img_float
    normalized_u8 = np.clip(normalized, 0, 255).astype(np.uint8)
    
    # 4x Upscale to give SIFT the 16x16 pixel neighborhoods it needs
    upscaled = cv2.resize(normalized_u8, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    return clahe.apply(upscaled)
    #return upscaled

def verify_live_scan(probe_img: np.ndarray, threshold_matches: int = 15):
    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Directory '{TEMPLATE_DIR}' does not exist.")

    probe_enhanced = enhance_image(probe_img)
    sift = cv2.SIFT_create(edgeThreshold=50)
    kp_probe, desc_probe = sift.detectAndCompute(probe_enhanced, None)
    
    if desc_probe is None or len(desc_probe) < 2:
        return False, 0, None, probe_enhanced, kp_probe, None, None, None

    best_match_count = 0
    best_match_name = None
    best_template_img = None
    best_kp_template = None
    best_match_points = None

    for file in os.listdir(TEMPLATE_DIR):
        if not file.endswith(".bin"):
            continue
            
        template_path = TEMPLATE_DIR / file
        raw_data = np.fromfile(template_path, dtype=np.uint8)
        
        if len(raw_data) < IMG_SIZE:
            continue
            
        template_img = raw_data[:IMG_SIZE].reshape((57, 70))
        template_enhanced = enhance_image(template_img)
        
        kp_template, desc_template = sift.detectAndCompute(template_enhanced, None)
        
        if desc_template is None or len(desc_template) < 2:
            continue
            
        matches = cv2.FlannBasedMatcher({'algorithm': 1, 'trees': 10}, {}).knnMatch(desc_probe, desc_template, k=2)
        
        good_matches = []
        for match_tuple in matches:
            if len(match_tuple) == 2:
                p, q = match_tuple
                if p.distance < 0.72 * q.distance:
                    good_matches.append(p)
        
        # --- 1. STRICT UNIQUENESS FILTER (Force 1-to-1) ---
        # Sort by distance so we keep the mathematically strongest match for a point
        good_matches = sorted(good_matches, key=lambda x: x.distance)
        unique_matches = []
        seen_template_indices = set()
        
        for m in good_matches:
            # m.trainIdx is the ID of the point on the stored template
            if m.trainIdx not in seen_template_indices:
                seen_template_indices.add(m.trainIdx)
                unique_matches.append(m)

        # --- 2. GEOMETRIC VERIFICATION (RANSAC) ---
        # Filters out false positives by ensuring the matched points move 
        # together as a rigid surface (lines won't cross wildly).
        final_match_points = []
        
        # RANSAC requires at least 4 points to calculate the geometry
        if len(unique_matches) >= 4:
            src_pts = np.float32([kp_probe[m.queryIdx].pt for m in unique_matches]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp_template[m.trainIdx].pt for m in unique_matches]).reshape(-1, 1, 2)
            
            # Find the homography matrix; mask returns 1 for good geometry, 0 for outliers
            M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            
            if mask is not None:
                for i, m in enumerate(unique_matches):
                    if mask[i][0] == 1: # If RANSAC says it's a geometrically valid point
                        final_match_points.append(m)
                        
        current_match_count = len(final_match_points)
        
        if current_match_count > best_match_count:
            best_match_count = current_match_count
            best_match_name = file
            best_template_img = template_enhanced
            best_kp_template = kp_template
            best_match_points = final_match_points # <-- Update this variable reference

    accepted = best_match_count >= threshold_matches
    return accepted, best_match_count, best_match_name, probe_enhanced, kp_probe, best_template_img, best_kp_template, best_match_points

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    if not TEMPLATE_DIR.exists():
        print(f"[!] Warning: The directory '{TEMPLATE_DIR}' does not exist.")
        sys.exit(1)
        
    dev = setup_sensor()

    try:
        while True:
            print("\n" + "="*50)
            print("Ready for live SIFT verification.")
            print("Press ENTER to scan, or type 'q' to quit.")
            choice = input("> ").strip().lower()

            if choice == 'q':
                break
                
            probe = capture_single_image(dev)
            
            try:
                # threshold_matches is set to 12. Adjust this up/down based on your tests.
                (accepted, match_count, match_name, 
                 probe_img, kp_probe, template_img, kp_template, mp) = verify_live_scan(probe, threshold_matches=12)
                
                if accepted:
                    print(f"\n>>> ✅ ACCEPTED! <<<")
                    print(f"    Best Match: {match_name}")
                    print(f"    Total Strong Matches: {match_count}")
                else:
                    print(f"\n>>> ❌ ACCESS DENIED! <<<")
                    print(f"    Highest Match: {match_name if match_name else 'None'}")
                    print(f"    Total Strong Matches: {match_count}")

                # --- VISUAL DISPLAY LOGIC ---
                if template_img is not None and match_count > 0:
                    # Draw lines connecting the matching keypoints
                    result_img = cv2.drawMatches(probe_img, kp_probe, template_img, kp_template, mp, None, flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
                    print("\n[i] Displaying match comparison. Press any key on the image window to continue.")
                    cv2.imshow("Match Comparison (Probe vs Template)", result_img)
                else:
                    # Draw just the live scan if no features or templates matched
                    print("\n[i] Displaying live scan. Press any key on the image window to continue.")
                    cv2.imshow("Live Scan (No Match)", probe_img)
                    
                cv2.waitKey(0)
                cv2.destroyAllWindows()
                
            except FileNotFoundError as e:
                print(f"\n[!] Error: {e}")
                
    except KeyboardInterrupt:
        log("Process aborted by user.")
    finally:
        usb.util.release_interface(dev, 0)
        log("Released Egis sensor.")