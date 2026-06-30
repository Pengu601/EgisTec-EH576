import usb.core
import usb.util
import time
import os
import sys
import statistics

# Hardware Constants
VID, PID = 0x1c7a, 0x0576
EP_OUT, EP_IN = 0x01, 0x82
DATASET_DIR = "raw_fingerprints"
IMG_SIZE = 3990 # in bytes, image is 70x57 pixels

#necessary to tell sensor to be ready to read finger
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

#used during polling to keep sensor active
REPEAT_SEQUENCE = [
    "45474953632c020057", "45474953602d00", "45474953626703",
    "45474953600f00", "45474953632c020013"
]

def log(msg):
    # Only print standard logs, avoid flooding the screen during the fast loop
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

#calculate variance to see if finger is present on sensor
def is_finger_present(image_bytes):
    
    if len(image_bytes) < IMG_SIZE:
        return False
    
    # slightly higher threshold (12.0) just to be safe against noise
    try:
        variance = statistics.pvariance(image_bytes)
        return variance > 12.0
    except statistics.StatisticsError:
        return False

def setup_environment():
    if not os.path.exists(DATASET_DIR):
        os.makedirs(DATASET_DIR)
        log(f"Created dataset directory: {DATASET_DIR}/")

def run_harvest(target_count=100):
    log("start")
    
    dev = usb.core.find(idVendor=VID, idProduct=PID) #find egis sensor
    if dev is None:
        log("Sensor not found.")
        sys.exit(1)

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass 

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    log("claimed sensor.")

    log("\nstart init sequence")
    for cmd in INIT_SEQUENCE:
        expected_len = IMG_SIZE if cmd == "45474953640f96" else 64
        execute_cmd(dev, cmd, read_len=expected_len)
    
    log("\n[+] finished init")
    
    capture_count = 0
    try:
        while capture_count < target_count:
            sys.stdout.write(f"\r[*] Awaiting capture {capture_count + 1}/{target_count}... Place finger on sensor.")
            sys.stdout.flush()
            
            touch_detected = False
            while not touch_detected:
                for cmd in REPEAT_SEQUENCE:
                    execute_cmd(dev, cmd)
                
                # Send Poll command to prep the image buffer
                execute_cmd(dev, "45474953600000", timeout=500)
                
                # Immediately request the 3990-byte image
                dev.write(EP_OUT, bytes.fromhex("45474953640f96"), timeout=1000)
                
                image_buffer = bytearray()
                start_t = time.time()
                
                # Fetch the image chunks
                while time.time() - start_t < 0.5:
                    try:
                        chunk = dev.read(EP_IN, 4096, timeout=100)
                        if chunk:
                            image_buffer.extend(chunk)
                            if len(image_buffer) >= IMG_SIZE:
                                break
                    except usb.core.USBTimeoutError:
                        break
                
                # If we got a full image, perform the software variance check
                if len(image_buffer) >= IMG_SIZE:
                    img_data = image_buffer[:IMG_SIZE]
                    
                    if is_finger_present(img_data):
                        variance = statistics.pvariance(img_data)
                        log(f"\ndetected finger (Variance: {variance:.2f})")
                        
                        filename = f"{DATASET_DIR}/finger_{capture_count + 1:03d}.bin"
                        with open(filename, "wb") as f:
                            f.write(img_data)
                        
                        log(f"Saved fingerprint to {filename}")
                        capture_count += 1
                        touch_detected = True
                        
                        log("lift your finger.")
                        # Wait a moment to ensure user lifts finger before checking again
                        time.sleep(1.5) 
                        
            time.sleep(0.05) 
                
    except KeyboardInterrupt:
        log("aborted")
    finally:
        usb.util.release_interface(dev, 0)
        

if __name__ == "__main__":
    setup_environment()
    run_harvest(target_count=100)