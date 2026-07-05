import usb.core
import usb.util
import time
import os
import sys

# Hardware Constants
VID, PID = 0x1c7a, 0x0576
EP_OUT, EP_IN = 0x01, 0x82
DATASET_DIR = "background_noise" # Changed directory name
IMG_SIZE = 3990 # in bytes, image is 70x57 pixels

#necessary to tell sensor to be ready to read
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

def setup_environment():
    if not os.path.exists(DATASET_DIR):
        os.makedirs(DATASET_DIR)
        log(f"Created dataset directory: {DATASET_DIR}/")

def run_harvest(target_count=10):
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
    
    try:
        for capture_count in range(target_count):
            sys.stdout.write(f"\r[*] Capturing background noise {capture_count + 1}/{target_count}...")
            sys.stdout.flush()
            
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
            
            # Save the image without checking for a finger
            if len(image_buffer) >= IMG_SIZE:
                img_data = image_buffer[:IMG_SIZE]
                
                filename = f"{DATASET_DIR}/noise_capture_{capture_count + 1:03d}.bin"
                with open(filename, "wb") as f:
                    f.write(img_data)
                
                log(f"\nSaved background noise to {filename}")
            else:
                log(f"\nFailed to capture full image for {capture_count + 1}. Buffer size: {len(image_buffer)}")
            
            # Wait 1 second before the next capture
            time.sleep(1.0)
                
    except KeyboardInterrupt:
        log("\naborted")
    finally:
        usb.util.release_interface(dev, 0)

if __name__ == "__main__":
    setup_environment()
    run_harvest(target_count=10)