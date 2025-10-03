import usb.core, usb.util, time
import sys
import threading
from datetime import datetime

VENDOR = 0x1c7a
PRODUCT = 0x0576

dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
if dev is None:
    raise ValueError("Device not found")

try:
    cfg = dev.get_active_configuration()
except usb.core.USBError as e:
    print(f"Permission error accessing device: {e}")
    print("Try running with sudo or setting up udev rules for the device")
    print(f"Device found: Bus {dev.bus:03d} Device {dev.address:03d}: ID {dev.idVendor:04x}:{dev.idProduct:04x}")
    sys.exit(1)

print(f"Device configuration: {cfg}")
intf = cfg[(0,0)]

if dev.is_kernel_driver_active(intf.bInterfaceNumber):
    print("Detaching kernel driver...")
    dev.detach_kernel_driver(intf.bInterfaceNumber)
usb.util.claim_interface(dev, intf.bInterfaceNumber)

bulk_in = 0x82
bulk_out = 0x01
intr_in = [0x83, 0x84]

# Initialize log file
log_file = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
data_received = False

def read_endpoint(ep, max_len, timeout=2000):
    global data_received
    try:
        data = dev.read(ep, max_len, timeout=timeout)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] *** DATA RECEIVED *** {len(data)} bytes from {hex(ep)}")
        print(f"Data: {' '.join(f'{b:02x}' for b in data)}")
        
        # Save to individual endpoint files
        with open(f"ep_{hex(ep)}.bin", "ab") as f:
            f.write(data)
        
        # Save to log with timestamp
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] EP {hex(ep)}: {' '.join(f'{b:02x}' for b in data)}\n")
        
        data_received = True
        return data
    except usb.core.USBError as e:
        if 'timeout' not in str(e).lower():
            # Only print non-timeout errors
            print(f"Error reading {hex(ep)}: {e}")
        return None

def try_init_commands():
    """Try EgisTec-specific initialization commands from EH575 research"""
    # EgisTec commands from libfprint EH575 driver
    # All commands start with "EGIS" header: 0x45, 0x47, 0x49, 0x53
    init_commands = [
        # Basic POST_INIT sequence (try first)
        b'\x45\x47\x49\x53\x60\x00\xfc',  # POST_INIT command 1
        b'\x45\x47\x49\x53\x60\x01\xfc',  # POST_INIT command 2 (checks device state)
        
        # If device needs PRE_INIT, these are the first few commands
        b'\x45\x47\x49\x53\x60\x00\x00',  # PRE_INIT command 1
        b'\x45\x47\x49\x53\x60\x01\x00',  # PRE_INIT command 2
        b'\x45\x47\x49\x53\x61\x0a\xfd',  # PRE_INIT command 3
        
        # Key activation commands
        b'\x45\x47\x49\x53\x64\x14\xec',  # Image capture command (expects large response)
        b'\x45\x47\x49\x53\x73\x14\xec',  # Another image command variant
    ]
    
    print("Trying EgisTec initialization commands (from EH575 research)...")
    for i, cmd in enumerate(init_commands):
        try:
            dev.write(bulk_out, cmd, timeout=1000)
            print(f"Sent EgisTec command {i+1}: {' '.join(f'{b:02x}' for b in cmd)}")
            time.sleep(0.1)
            
            # Try to read response - use larger buffer for image commands
            max_len = 6000 if cmd[4] in [0x64, 0x73] else 64
            timeout = 3000 if cmd[4] in [0x64, 0x73] else 1000
            
            for ep in [bulk_in] + intr_in:
                data = read_endpoint(ep, max_len, timeout=timeout)
                if data and len(data) > 10:
                    print(f"*** Got significant response ({len(data)} bytes) from command {i+1}! ***")
        except Exception as e:
            print(f"EgisTec command {i+1} failed: {e}")
        time.sleep(0.3)

# Try initialization first
try_init_commands()

# Poll loop
print("\n" + "="*60)
print("CONTINUOUS MONITORING - Touch the sensor now...")
print("Press Ctrl+C to stop")
print("="*60)

try:
    poll_count = 0
    last_status = time.time()
    
    while True:
        poll_count += 1
        
        # Show status every 5 seconds
        if time.time() - last_status > 5:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring... (poll #{poll_count})")
            last_status = time.time()
        
        # Poll interrupt endpoints (higher priority)
        for ep in intr_in:
            data = read_endpoint(ep, 64, timeout=100)
            if data:
                print(f"Interrupt data detected on {hex(ep)}!")
        
        # Poll bulk endpoint
        data = read_endpoint(bulk_in, 512, timeout=100)
        if data:
            print(f"Bulk data detected on {hex(bulk_in)}!")
        
        time.sleep(0.05)  # 50ms delay between polls
        
except KeyboardInterrupt:
    print("\nStopping...")

# Cleanup
print("Cleaning up...")
usb.util.release_interface(dev, intf.bInterfaceNumber)
try:
    dev.attach_kernel_driver(intf.bInterfaceNumber)
except:
    pass

if data_received:
    print(f"\n*** SUCCESS! Data was captured and saved to {log_file} ***")
    print("Check the ep_0x**.bin files for raw data")
else:
    print("\nNo data received. The sensor might need different initialization.")
    print("Try touching the sensor multiple times or holding your finger on it longer.")

print("Done")
