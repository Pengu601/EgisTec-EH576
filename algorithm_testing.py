import os
import cv2
import numpy as np

def load_and_enhance_bin(file_path):
    """
    Reads the raw .bin dump, reshapes to 57x70 (H,W), 
    and normalizes contrast so SIFT can detect ridges.
    """
    # 1. Read raw binary data
    raw_data = np.fromfile(file_path, dtype=np.uint8)
    
    # 2. Reshape to Height=57, Width=70 (3990 bytes total)
    img = raw_data[:3990].reshape((57, 70))
    
    # 3. Enhance contrast (97-135 -> 0-255)
    img_float = img.astype(np.float32)
    min_val, max_val = np.min(img_float), np.max(img_float)
    if max_val > min_val:
        normalized = ((img_float - min_val) / (max_val - min_val) * 255.0)
    else:
        normalized = img_float
        
    normalized_u8 = np.clip(normalized, 0, 255).astype(np.uint8)
    
    # 4. Apply CLAHE for local ridge isolation
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    return normalized_u8

# Load the probe/sample image using the custom binary loader
sample_path = "//home//pengu//Documents//GitHub//EgisTec EH576//testing_fingerprints//left_index_001.bin"
sample = load_and_enhance_bin(sample_path)

best_score = 0
filename = None
image = None
kp1, kp2, mp = None, None, None

raw_dir = "//home//pengu//Documents//GitHub//EgisTec EH576//raw_fingerprints"

# Process only .bin files in the directory
for file in os.listdir(raw_dir):
    if not file.endswith(".bin"):
        continue
        
    fingerprint_path = os.path.join(raw_dir, file)
    fingerprint_image = load_and_enhance_bin(fingerprint_path)
    
    # cv2.imshow("sample", fingerprint_image)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

    sift = cv2.SIFT_create()
    keypoints_1, descriptors_1 = sift.detectAndCompute(sample, None)
    keypoints_2, descriptors_2 = sift.detectAndCompute(fingerprint_image, None)
    
    # Guard against completely blank/noisy images where SIFT finds nothing
    if descriptors_1 is None or descriptors_2 is None or len(descriptors_1) < 2 or len(descriptors_2) < 2:
        print("fail")
        continue
    
    # print(descriptors_1)
    matches = cv2.FlannBasedMatcher({'algorithm': 1, 'trees': 10}, {}).knnMatch(descriptors_1, descriptors_2, k=2)
    
    # print(matches)
    match_points = []
    for match_tuple in matches:
        if len(match_tuple) == 2:
            p, q = match_tuple
            # NOTE: 0.1 is an extremely strict ratio test. 
            # If you get 0 matches, increase this closer to Lowe's standard (0.75)
            if p.distance < 0.55 * q.distance:
                match_points.append(p)
    # print(match_points)       
    keypoints = 0
    if len(keypoints_1) < len(keypoints_2):
        keypoints = len(keypoints_1)
    else:
        keypoints = len(keypoints_2)
        
    if keypoints == 0:
        continue
        
    score = (len(match_points) / keypoints) * 100
    
    if score > best_score:
        best_score = score
        filename = file
        image = fingerprint_image
        kp1, kp2, mp = keypoints_1, keypoints_2, match_points

print("BEST MATCH: " + str(filename))
print("SCORE: " + str(best_score))

if image is not None:
    result = cv2.drawMatches(sample, kp1, image, kp2, mp, None)
    
    # Fix: cv2.resize requires the 'dsize' parameter (can be None if using fx/fy)
    result = cv2.resize(result, None, fx=4, fy=4)
    
    cv2.imshow("Result", result)
    cv2.waitKey(0)
    
    # Fix: Typo in destroyAllWindows
    cv2.destroyAllWindows()
else:
    print("No valid matches found to display.")