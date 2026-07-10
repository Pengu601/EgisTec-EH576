import numpy as np
import sys
import time

#
sys.path.insert(0, ".")
from testing import setup_sensor, execute_cmd, REPEAT_SEQUENCE, IMG_SIZE

N_FRAMES = 20


def capture_raw_frame(dev):
    for cmd in REPEAT_SEQUENCE:
        execute_cmd(dev, cmd)
    execute_cmd(dev, "45474953600000", timeout=500)
    dev.write(0x01, bytes.fromhex("45474953640f96"), timeout=1000)

    buf = bytearray()
    start = time.time()
    while time.time() - start < 0.5:
        try:
            chunk = dev.read(0x82, 4096, timeout=100)
            if chunk:
                buf.extend(chunk)
                if len(buf) >= IMG_SIZE:
                    break
        except Exception:
            break
    return np.frombuffer(bytes(buf[:IMG_SIZE]), dtype=np.uint8).reshape((70, 57)).astype(np.float32)


def main():
    print("Make sure NOTHING is touching the sensor.")
    input("Press ENTER to begin flat-field capture...")

    dev = setup_sensor()
    frames = []
    for i in range(N_FRAMES):
        frame = capture_raw_frame(dev)
        frames.append(frame)
        print(f"Captured frame {i+1}/{N_FRAMES}")
        time.sleep(0.1)

    flat_field = np.mean(frames, axis=0)
    np.save("flat_field.npy", flat_field)
    print(f"Saved flat_field.npy (mean={flat_field.mean():.2f}, std={flat_field.std():.2f})")

main()