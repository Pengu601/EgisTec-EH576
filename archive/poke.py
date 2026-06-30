import usb.core
import usb.util
import time

VENDOR_ID = 0x1c7a
PRODUCT_ID = 0x0576
CMD_WRITE_REG = 0x61
CMD_BURST_WRITE = 0x63
CMD_GET_FRAME = 0x64
HEADER = [0x45, 0x47, 0x49, 0x53] 
REQUEST_SIZE = 32768

class EgisScanner:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if self.dev is None: raise ValueError("Device not found.")
        if self.dev.is_kernel_driver_active(0):
            try: self.dev.detach_kernel_driver(0)
            except: pass
        self.dev.set_configuration()
        self.ep_out = 0x01
        self.ep_in = 0x82

    def send_raw(self, payload):
        self.dev.write(self.ep_out, payload)
        return list(self.dev.read(self.ep_in, 64, timeout=2000))

    def read_reg(self, reg):
        payload = HEADER + [0x60, reg, 0x00]
        resp = self.send_raw(payload)
        return resp[5]

    def write_reg(self, reg, val):
        payload = HEADER + [CMD_WRITE_REG, reg, val]
        self.send_raw(payload)
        time.sleep(0.01)

    def write_burst(self, start_reg, data_bytes):
        print(f"   Burst Write to 0x{start_reg:02X}...")
        payload = HEADER + [CMD_BURST_WRITE, start_reg, len(data_bytes)] + list(data_bytes)
        self.send_raw(payload)
        time.sleep(0.02)

    def get_image(self, size):
        self.dev.write(self.ep_out, HEADER + [CMD_GET_FRAME, (size >> 8) & 0xFF, size & 0xFF])
        return self.dev.read(self.ep_in, size, timeout=5000)

if __name__ == "__main__":
    scanner = EgisScanner()
    
    # 1. IDENTIFY CHIP
    print("--- 1. Register Dump (Identity) ---")
    # Reading the first 5 registers often reveals the Chip ID
    for r in range(5):
        val = scanner.read_reg(r)
        print(f"   Reg 0x{r:02X}: 0x{val:02X}")

    # 2. FULL SETUP (As verified)
    print("--- 2. Sending Full Configuration ---")
    analog_config = [0x83, 0x24, 0x00, 0x44, 0x0F, 0x08, 0x20, 0x20, 0x01, 0x0F, 0x12]
    scanner.write_burst(0x09, analog_config)
    
    magic_bytes = [0x0E, 0x36, 0x04, 0x0A, 0x2E, 0x04]
    scanner.write_burst(0x26, magic_bytes)

    # 3. THE TOGGLE TRICK
    print("--- 3. Waking Up (Toggling Mode 0x23) ---")
    
    # Try 1: Write 1 (Active?)
    print("   Writing 0x23 = 0x01...")
    scanner.write_reg(0x23, 0x01)
    status = scanner.read_reg(0x40)
    print(f"   Status: 0x{status:02X}")

    time.sleep(0.1)

    # Try 2: Write 0 (Default?)
    print("   Writing 0x23 = 0x00...")
    scanner.write_reg(0x23, 0x00)
    status = scanner.read_reg(0x40)
    print(f"   Status: 0x{status:02X}")

    # 4. CAPTURE (Regardless of status, just to check)
    print("--- 4. Capture Attempt ---")
    try:
        data = scanner.get_image(REQUEST_SIZE)
        with open("fingerprint.bin", "wb") as f:
            f.write(data)
        print(f"Captured {len(data)} bytes. Run view script!")
    except Exception as e:
        print(f"Capture Error: {e}")