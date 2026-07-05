import os
from PIL import Image

# Sensor dimensions we extracted from Marcel's C header
WIDTH = 70
HEIGHT = 57
INPUT_DIR = "background_noise"
OUTPUT_DIR = "background_png"

def convert_bin_to_png():
    if not os.path.exists(INPUT_DIR):
        print(f"[-] Directory '{INPUT_DIR}' not found.")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[+] Created output directory: {OUTPUT_DIR}/")

    count = 0
    for filename in os.listdir(INPUT_DIR):
        if filename.endswith(".bin"):
            in_path = os.path.join(INPUT_DIR, filename)
            out_path = os.path.join(OUTPUT_DIR, filename.replace(".bin", ".png"))

            with open(in_path, "rb") as f:
                raw_data = f.read()

            # Ensure the file is exactly the size of one frame
            if len(raw_data) == WIDTH * HEIGHT:
                # 'L' mode stands for 8-bit pixels, black and white
                img = Image.frombytes('L', (WIDTH, HEIGHT), raw_data)
                
                # The sensor might read the image upside down or mirrored depending 
                # on how it's mounted in the laptop chassis. 
                # Uncomment these if your fingerprint looks flipped!
                # img = img.transpose(Image.FLIP_TOP_BOTTOM)
                
                img.save(out_path)
                count += 1
            else:
                print(f"[-] Skipping {filename}: Invalid size ({len(raw_data)} bytes). Expected {WIDTH * HEIGHT}.")

    print(f"[+] Successfully converted {count} raw fingerprints to PNG!")
    print(f"[+] You can view them in the '{OUTPUT_DIR}' folder.")

if __name__ == "__main__":
    convert_bin_to_png()