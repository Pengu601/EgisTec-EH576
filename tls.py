import usb.core
import usb.util
import ssl
import sys
import time

# Device Hardware Parameters
VID, PID = 0x1c7a, 0x0576
EP_OUT, EP_IN = 0x01, 0x82

class SecureSensorDiagnostics:
    def __init__(self):
        self.dev = None
        self.ssl_context = None
        self.incoming_bio = None
        self.outgoing_bio = None
        self.tls_object = None

    def connect_hardware(self):
        print("[+] Locating EH576 sensor...")
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if not self.dev:
            raise RuntimeError("Sensor not found. Ensure it is connected and power-cycled.")
        
        # Reset the device state completely to clear any previous failed states
        self.dev.reset()
        time.sleep(0.5)
        
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        print("[+] USB Interface claimed successfully.")

    def send_pre_flight_boot_packet(self):
        print("[+] Draining hardware boot status buffer...")
        try:
            # The sensor automatically queues a 27-byte status on boot.
            # We must pull it to clear the pipe before starting TLS.
            boot_status = self.dev.read(EP_IN, 64, timeout=1000)
            print(f" -> Hardware Boot Status Cleared: {bytes(boot_status).hex()}")
            time.sleep(0.1) # Brief pause before hammering it with TLS
        except usb.core.USBTimeoutError:
            print(" -> No boot status waiting in the buffer. Proceeding...")
        except usb.core.USBError as e:
            print(f"[-] USB Error during buffer drain: {e}")

    def init_tls_layer(self):
        print("[+] Initializing Memory-buffered TLS 1.2 Context...")
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        self.ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Memory pipes isolate raw TLS frame generation away from network sockets
        self.incoming_bio = ssl.MemoryBIO()
        self.outgoing_bio = ssl.MemoryBIO()
        
        self.tls_object = self.ssl_context.wrap_bio(
            self.incoming_bio, self.outgoing_bio, server_hostname="egistec"
        )

    def run_handshake_loop(self):
        print("\n[+] --- STARTING SECURE TLS HANDSHAKE OVER USB ---")
        
        try:
            while True:
                try:
                    self.tls_object.do_handshake()
                    print("\n[SUCCESS] TLS Handshake Completed! Secure tunnel established.")
                    return True
                except ssl.SSLWantReadError:
                    # SSL engine needs to read data, but check if it placed data to send first (e.g., Client Hello)
                    out_data = self.outgoing_bio.read()
                    if out_data:
                        print(f"[PC -> SENSOR] Dispatched {len(out_data)} bytes of TLS payload...")
                        self.dev.write(EP_OUT, out_data)

                    # Now pull data out of the physical USB endpoint and stream it into the SSL engine
                    try:
                        incoming_usb = self.dev.read(EP_IN, 8192, timeout=2000)
                        if incoming_usb:
                            print(f"[SENSOR -> PC] Received {len(incoming_usb)} bytes from USB.")
                            self.incoming_bio.write(bytes(incoming_usb))
                    except usb.core.USBTimeoutError:
                        print("[-] USB Read Timeout. Sensor failed to respond to the TLS frame.")
                        return False
                        
                except ssl.SSLWantWriteError:
                    # SSL engine simply needs to push data outward
                    out_data = self.outgoing_bio.read()
                    if out_data:
                        print(f"[PC -> SENSOR] Dispatched {len(out_data)} bytes of TLS payload...")
                        self.dev.write(EP_OUT, out_data)
                        
                except ssl.SSLError as handshake_error:
                    print(f"\n[FATAL] SSL Handshake Protocol Error: {handshake_error}")
                    print(" -> Suggestion: Check if OpenSSL version requires explicitly setting a cipher suite.")
                    return False
        finally:
            pass

    def cleanup(self):
        if self.dev:
            print("[+] Releasing interface and closing handle.")
            usb.util.release_interface(self.dev, 0)

if __name__ == "__main__":
    client = SecureSensorDiagnostics()
    try:
        client.connect_hardware()
        client.send_pre_flight_boot_packet()
        client.init_tls_layer()
        client.run_handshake_loop()
    except KeyboardInterrupt:
        print("\n[-] Execution interrupted by user.")
    except Exception as fatal_err:
        print(f"\n[!] Runtime Failure: {fatal_err}")
    finally:
        client.cleanup()