import usb.core
import usb.util
import time
import sys
from tlslite import TLSConnection

# Device Configuration
VID, PID = 0x1c7a, 0x0576
EP_OUT, EP_IN = 0x01, 0x82

# ==========================================
# 1. USB-to-SOCKET ABSTRACTION LAYER
# ==========================================
class USBDummySocket:
    """Tricks tlslite-ng into treating raw USB endpoints as a TCP socket."""
    def __init__(self, dev):
        self.dev = dev
        self.timeout = 2000

    def send(self, data):
        try:
            self.dev.write(EP_OUT, data, timeout=self.timeout)
            return len(data)
        except Exception as e:
            print(f"[-] USB Send Error: {e}")
            return 0

    def sendall(self, data):
        self.send(data)

    def recv(self, size):
        try:
            # We read from the bulk IN endpoint. Size is a suggestion, 
            # but USB bulk usually returns what is currently in the buffer.
            data = self.dev.read(EP_IN, size, timeout=self.timeout)
            return bytes(data)
        except usb.core.USBTimeoutError:
            return b""
        except Exception as e:
            print(f"[-] USB Recv Error: {e}")
            return b""

    def close(self):
        pass

    def getsockname(self):
        return ("127.0.0.1", 443)


# ==========================================
# 2. CRYPTOGRAPHIC CALLBACK
# ==========================================
def psk_callback(identity, identityHint):
    """
    tlslite-ng calls this when the sensor attempts to connect.
    It expects a bytearray of the symmetric key.
    """
    print(f"[*] TLS Engine requested PSK for identity: {identity}")
    
    # [!] PASTE YOUR EXTRACTED HEX KEY HERE
    extracted_hex_key = "INSERT_YOUR_EXTRACTED_MASTER_KEY_HEX_HERE" 
    
    try:
        return bytearray.fromhex(extracted_hex_key)
    except ValueError:
        print("[-] Invalid Hex Key provided in script!")
        sys.exit(1)


# ==========================================
# 3. MAIN DRIVER ROUTINE
# ==========================================
def run_driver():
    print("[+] Locating EH576 sensor...")
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if not dev:
        print("[-] Sensor not found.")
        return
    
    dev.reset()
    time.sleep(0.5)
    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    print("[+] USB Interface claimed.")

    print("[+] Waking sensor control logic (Endpoint 0)...")
    try:
        dev.ctrl_transfer(0x21, 0x09, 0x0000, 0x0000, None)
        time.sleep(0.1)
    except Exception:
        pass # Ignore stall errors

    print("[+] Instantiating USB-Socket Bridge...")
    usb_sock = USBDummySocket(dev)
    
    # Wrap our fake USB socket in the TLS Connection manager
    tls_conn = TLSConnection(usb_sock)

    print("\n[+] --- WAITING FOR SENSOR CLIENT HELLO ---")
    try:
        # We act as the Server. We hand it our PSK callback so it can authenticate the sensor.
        tls_conn.handshakeServer(sharedKeyCallback=psk_callback)
        print("\n[SUCCESS] TLS-PSK Handshake Completed! Secure tunnel established.")
    except Exception as e:
        print(f"\n[FATAL] Handshake Failed: {e}")
        usb.util.release_interface(dev, 0)
        return

    # ==========================================
    # 4. ENCRYPTED STATE MACHINE (INSIDE TUNNEL)
    # ==========================================
    def secure_send(hex_str):
        tls_conn.write(bytes.fromhex(hex_str))
        
    def secure_recv():
        # tlslite-ng handles decrypting the underlying USB stream
        return tls_conn.read(4096)

    print("\n[+] Injecting Egis Initialization Sequence...")
    init_sequence = [
        "4547495360006d", # Unlock
        "45474953c00400", # Power
        "4547495363605003", # Config Window
        "45474953600020"  # Pre-flight
    ]

    for cmd in init_sequence:
        secure_send(cmd)
        time.sleep(0.05)
        ack = secure_recv()
        if ack:
            print(f" -> Init Ack: {ack.hex()}")

    print("\n[!] SENSOR ARMED. Polling for finger... (Press Ctrl+C to stop)")
    
    try:
        while True:
            # Poll Command
            secure_send("454749536414ec") 
            resp = secure_recv()
            
            if resp:
                # Look for the 'Finger Present' signature in the decrypted response
                if b"\x00\xab\x01" in resp or b"\xab\x01" in resp:
                    print(f"\n[!] TOUCH DETECTED! Flags: {resp.hex()}")
                    
                    print("[+] Sending Image Drain Command (0f 96)...")
                    secure_send("454749530f96")
                    
                    # Accumulate chunks
                    image_buffer = bytearray()
                    start_t = time.time()
                    
                    print("[+] Streaming secure image payload...")
                    while time.time() - start_t < 1.5:
                        chunk = secure_recv()
                        if chunk:
                            image_buffer.extend(chunk)
                            if len(image_buffer) >= 5356:
                                break
                                
                    print(f"[*] Captured {len(image_buffer)} bytes!")
                    
                    if len(image_buffer) >= 5356:
                        with open("raw_capture.bin", "wb") as f:
                            f.write(image_buffer)
                        print("[+] Decrypted frame saved to raw_capture.bin")
                        
                        # Send Acknowledge
                        secure_send("45474953612d")
                        break
            
            time.sleep(0.05)
            sys.stdout.write(".")
            sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n[-] Capture aborted.")
    finally:
        tls_conn.close()
        usb.util.release_interface(dev, 0)
        print("[+] Hardware released.")

if __name__ == "__main__":
    run_driver()