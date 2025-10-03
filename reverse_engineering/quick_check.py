#!/usr/bin/env python3
"""
Quick file size check for EgisTec captures
"""
import os
import glob

def check_files():
    print("📁 File Size Analysis:")
    print("-" * 40)
    
    # Check all .bin files
    pattern = "*.bin"
    files = glob.glob(pattern)
    
    if not files:
        print("No .bin files found!")
        return
    
    # Get file sizes
    file_sizes = []
    for filepath in files:
        try:
            size = os.path.getsize(filepath)
            file_sizes.append((filepath, size))
        except OSError as e:
            print(f"Error reading {filepath}: {e}")
    
    # Sort by size (largest first)
    file_sizes.sort(key=lambda x: x[1], reverse=True)
    
    print(f"Found {len(file_sizes)} files:")
    for filepath, size in file_sizes:
        print(f"  {filepath}: {size} bytes")
        
        # Check first few bytes if file exists and is readable
        if size > 0:
            try:
                with open(filepath, 'rb') as f:
                    first_bytes = f.read(16)
                    hex_str = ' '.join(f'{b:02x}' for b in first_bytes)
                    print(f"    First bytes: {hex_str}")
                    
                    # Check for SIGE header
                    if first_bytes[:4] == b'SIGE':
                        print(f"    ✅ SIGE header detected")
                    elif first_bytes[:4] == b'EGIS':
                        print(f"    ✅ EGIS header detected")
                    elif size > 5000:
                        print(f"    🖼️  LARGE FILE - Potential image data!")
                        
            except Exception as e:
                print(f"    ❌ Error reading content: {e}")
        
        print()

if __name__ == "__main__":
    check_files()
