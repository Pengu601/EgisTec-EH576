import usb.core #[cite: 5]
import usb.util #[cite: 5]
import time #[cite: 5]
import os #[cite: 5]
import sys #[cite: 5]
import statistics #[cite: 5]

# Hardware Constants
VID, PID = 0x1c7a, 0x0576 #[cite: 5]
EP_OUT, EP_IN = 0x01, 0x82 #[cite: 5]
DATASET_DIR = "testing_fingerprints" #[cite: 5]
IMG_SIZE = 3990 # in bytes, image is 70x57 pixels[cite: 5]

#necessary to tell sensor to be ready to read finger
INIT_SEQUENCE = [
    "45474953600000", "45474953600100", "454749536110fd", "45474953613502", #[cite: 5]
    "45474953618000", "45474953608000", "454749536110fc", "454749536301020f03", #[cite: 5]
    "45474953610c22", "45474953610983", "45474953632606066006052f06", #[cite: 5]
    "454749536110f4", "45474953610c44", "45474953615003", "45474953605000", #[cite: 5]
    "45474953640f96", # Flush Image Buffer[cite: 5]
    "45474953604000", "4547495363090b832400440f082020000052", #[cite: 5]
    "45474953632606066006052f06", "45474953612300", "45474953612438", #[cite: 5]
    "45474953612000", "45474953612145", "45474953600000", "45474953600100", #[cite: 5]
    "45474953632c020057", "45474953602d00", "45474953626703", #[cite: 5]
    "45474953600f00", "45474953632c020013" #[cite: 5]
]

#used during polling to keep sensor active
REPEAT_SEQUENCE = [
    "45474953632c020057", "45474953602d00", "45474953626703", #[cite: 5]
    "45474953600f00", "45474953632c020013" #[cite: 5]
]

def log(msg):
    # Only print standard logs, avoid flooding the screen during the fast loop
    if not msg.startswith("\r"): #[cite: 5]
        print(f"[{time.strftime('%H:%M:%S.%f')[:-3]}] {msg}") #[cite: 5]

def execute_cmd(dev, hex_cmd, read_len=64, timeout=1000):
    try:
        dev.write(EP_OUT, bytes.fromhex(hex_cmd), timeout=timeout) #[cite: 5]
    except Exception:
        return b"" #[cite: 5]
    time.sleep(0.01) #[cite: 5]
    try:
        return dev.read(EP_IN, read_len, timeout=timeout) #[cite: 5]
    except Exception:
        return b"" #[cite: 5]

#calculate variance to see if finger is present on sensor
def is_finger_present(image_bytes):
    
    if len(image_bytes) < IMG_SIZE: #[cite: 5]
        return False #[cite: 5]
    
    # slightly higher threshold (12.0) just to be safe against noise
    try:
        variance = statistics.pvariance(image_bytes) #[cite: 5]
        return variance > 12.0 #[cite: 5]
    except statistics.StatisticsError:
        return False #[cite: 5]

def setup_environment():
    if not os.path.exists(DATASET_DIR): #[cite: 5]
        os.makedirs(DATASET_DIR) #[cite: 5]
        log(f"Created dataset directory: {DATASET_DIR}/") #[cite: 5]

def run_harvest(target_count=10):
    log("start") #[cite: 5]
    
    dev = usb.core.find(idVendor=VID, idProduct=PID) #find egis sensor[cite: 5]
    if dev is None: #[cite: 5]
        log("Sensor not found.") #[cite: 5]
        sys.exit(1) #[cite: 5]

    try:
        if dev.is_kernel_driver_active(0): #[cite: 5]
            dev.detach_kernel_driver(0) #[cite: 5]
    except Exception:
        pass  #[cite: 5]

    dev.set_configuration() #[cite: 5]
    usb.util.claim_interface(dev, 0) #[cite: 5]
    log("claimed sensor.") #[cite: 5]

    log("\nstart init sequence") #[cite: 5]
    for cmd in INIT_SEQUENCE: #[cite: 5]
        expected_len = IMG_SIZE if cmd == "45474953640f96" else 64 #[cite: 5]
        execute_cmd(dev, cmd, read_len=expected_len) #[cite: 5]
    
    log("\n[+] finished init") #[cite: 5]
    
    capture_count = 0 #[cite: 5]
    try:
        while capture_count < target_count: #[cite: 5]
            sys.stdout.write(f"\r[*] Awaiting capture {capture_count + 1}/{target_count}... Place finger on sensor.") #[cite: 5]
            sys.stdout.flush() #[cite: 5]
            
            touch_detected = False #[cite: 5]
            while not touch_detected: #[cite: 5]
                for cmd in REPEAT_SEQUENCE: #[cite: 5]
                    execute_cmd(dev, cmd) #[cite: 5]
                
                # Send Poll command to prep the image buffer
                execute_cmd(dev, "45474953600000", timeout=500) #[cite: 5]
                
                # Immediately request the 3990-byte image
                dev.write(EP_OUT, bytes.fromhex("45474953640f96"), timeout=1000) #[cite: 5]
                
                image_buffer = bytearray() #[cite: 5]
                start_t = time.time() #[cite: 5]
                
                # Fetch the image chunks
                while time.time() - start_t < 0.5: #[cite: 5]
                    try:
                        chunk = dev.read(EP_IN, 4096, timeout=100) #[cite: 5]
                        if chunk: #[cite: 5]
                            image_buffer.extend(chunk) #[cite: 5]
                            if len(image_buffer) >= IMG_SIZE: #[cite: 5]
                                break #[cite: 5]
                    except usb.core.USBTimeoutError:
                        break #[cite: 5]
                
                # If we got a full image, perform the software variance check
                if len(image_buffer) >= IMG_SIZE: #[cite: 5]
                    img_data = image_buffer[:IMG_SIZE] #[cite: 5]
                    
                    if is_finger_present(img_data): #[cite: 5]
                        
                        # --- 0.25s SETTLING LOGIC ADDED HERE ---
                        log("\n[~] Initial touch detected. Waiting 250ms for finger to settle...")
                        time.sleep(0.25) 
                        
                        # Re-arm the sensor before requesting the new image
                        for cmd in REPEAT_SEQUENCE:
                            execute_cmd(dev, cmd)
                            
                        # Request the fresh, settled frame
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
                        
                        # Process and save the settled frame
                        if len(settled_buffer) >= IMG_SIZE:
                            settled_data = settled_buffer[:IMG_SIZE]
                            variance = statistics.pvariance(settled_data)
                            log(f"detected settled finger (Variance: {variance:.2f})")
                            
                            filename = f"{DATASET_DIR}/left_pink_{capture_count + 1:03d}.bin" #[cite: 5]
                            with open(filename, "wb") as f: #[cite: 5]
                                f.write(settled_data) 
                            
                            log(f"Saved fingerprint to {filename}") #[cite: 5]
                            capture_count += 1 #[cite: 5]
                            touch_detected = True #[cite: 5]
                            
                            log("lift your finger.") #[cite: 5]
                            # Wait a moment to ensure user lifts finger before checking again
                            time.sleep(1.5)  #[cite: 5]
                        
            time.sleep(0.05)  #[cite: 5]
                
    except KeyboardInterrupt:
        log("aborted") #[cite: 5]
    finally:
        usb.util.release_interface(dev, 0) #[cite: 5]
        

if __name__ == "__main__":
    setup_environment()
    run_harvest(target_count=10)