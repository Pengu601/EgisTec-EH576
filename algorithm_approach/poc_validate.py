import os
import glob
import numpy as np
import scipy.fftpack as fft
import scipy.ndimage

def load_bin_image(filepath):
    """
    Reads the raw hardware dump and prepares it for Fourier analysis.
    """
    with open(filepath, 'rb') as f:
        raw = f.read()
    if len(raw) != 3990:
        return None
        
    img_np = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    img_np = img_np.reshape((57, 70))
    
    # 1. Min-Max Normalization
    img_min = np.min(img_np)
    img_max = np.max(img_np)
    if img_max > img_min:
        img_np = (img_np - img_min) / (img_max - img_min)
        
    # 2. Hanning Window: The FFT assumes images wrap around like a sphere. 
    # To stop the sharp edges of the sensor from creating fake high-frequency waves,
    # we apply a window that gently fades the edges of the image to black.
    hanning_r = np.hanning(57)
    hanning_c = np.hanning(70)
    window = np.outer(hanning_r, hanning_c)
    
    # 3. Mean centering and windowing
    img_np = (img_np - np.mean(img_np)) * window
    
    return img_np

def calculate_poc_score(img1, img2):
    """
    Executes Rotation-Invariant Band-Passed POC using an angular sweep.
    """
    # 1. Fourier Transform of the Master Template
    F = fft.fft2(img1)
    F_shift = fft.fftshift(F)
    
    rows, cols = F_shift.shape
    center_row, center_col = rows // 2, cols // 2
    
    # 2. Construct the Donut Mask (Band-Pass Filter)
    r_high = int(rows * 0.65 / 2)
    c_high = int(cols * 0.65 / 2)
    r_low = 2
    c_low = 2
    
    mask = np.zeros((rows, cols))
    mask[center_row - r_high : center_row + r_high, 
         center_col - c_high : center_col + c_high] = 1
    mask[center_row - r_low : center_row + r_low, 
         center_col - c_low : center_col + c_low] = 0
         
    # Apply mask to the Master Template
    F_band = fft.ifftshift(F_shift * mask)
    
    best_score = 0.0
    
    # 3. Sweep through angles (-15 to +15 degrees in 3-degree steps)
    for angle in range(-15, 16, 3):
        # Physically rotate the live scan (reshape=False keeps the strict 57x70 hardware size)
        rotated_img2 = scipy.ndimage.rotate(img2, angle, reshape=False, order=3, mode='constant', cval=0.0)
        
        # Run the FFT on the rotated scan
        G = fft.fft2(rotated_img2)
        G_shift = fft.fftshift(G)
        G_band = fft.ifftshift(G_shift * mask)
        
        # Calculate Cross-Phase Spectrum
        G_conj = np.conj(G_band)
        cross_power = F_band * G_conj
        cross_phase = cross_power / (np.abs(cross_power) + 1e-8) 
        
        # Inverse FFT to find the ridge correlation peak
        r = fft.ifft2(cross_phase)
        score = np.max(np.real(r))
        
        if score > best_score:
            best_score = score
            
    return best_score

def run_poc_validation():
    dataset_dir = "D:\GitHub Projects\\EgisTec-EH576\\training_model\\scoofing_data\\raw_fingerprints"
    bin_files = sorted(glob.glob(os.path.join(dataset_dir, "*.bin")))
    
    if not bin_files:
        print(f"[-] No .bin files found in '{dataset_dir}'.")
        return

    # Group files by identity
    identities = {}
    for filepath in bin_files:
        filename = os.path.basename(filepath)
        parts = filename.replace('.bin', '').split('_')
        identity = "_".join(parts[:-1]) 
        
        if identity not in identities:
            identities[identity] = []
        identities[identity].append(filepath)

    print(f"[*] Found {len(identities)} unique fingers to test using Math (POC).")

    # Load all images into memory
    images = {}
    for identity, files in identities.items():
        images[identity] = []
        for filepath in files:
            img = load_bin_image(filepath)
            if img is not None:
                images[identity].append(img)

    match_scores = []
    imposter_scores = []

    print("\n=== EXECUTING PHASE-ONLY CORRELATION ===")
    for target_identity, target_scans in images.items():
        if len(target_scans) < 6:
            continue
            
        # Treat scan 01 as the strict "Master Template"
        master_template = target_scans[0]
        
        # Test Matches (Scans 02 through 10)
        for live_scan in target_scans[1:]:
            score = calculate_poc_score(master_template, live_scan)
            match_scores.append(score)
            
        # Test Imposters (All other fingers)
        for imposter_identity, imposter_scans in images.items():
            if imposter_identity == target_identity:
                continue
                
            for imposter_scan in imposter_scans:
                score = calculate_poc_score(master_template, imposter_scan)
                imposter_scores.append(score)

    avg_match = sum(match_scores) / len(match_scores)
    avg_imposter = sum(imposter_scores) / len(imposter_scores)
    
    # Note: For POC, HIGHER scores are better!
    print(f"\n[+] Total Valid Logins Tested: {len(match_scores)}")
    print(f"    -> Average Score for MATCHES:   {avg_match:.5f} (Higher is better)")
    print(f"    -> Min Score for MATCHES:       {min(match_scores):.5f}")
    
    print(f"\n[+] Total Imposter Attacks Tested: {len(imposter_scores)}")
    print(f"    -> Average Score for IMPOSTERS: {avg_imposter:.5f} (Lower is better)")
    print(f"    -> Max Score for IMPOSTERS:     {max(imposter_scores):.5f}")

    if min(match_scores) > max(imposter_scores):
        print("\n[SUCCESS] PERFECT MATHEMATICAL SEPARATION!")
    else:
        print("\n[WARNING] Overlap detected. We may need Band-Limited POC.")

if __name__ == "__main__":
    run_poc_validation()