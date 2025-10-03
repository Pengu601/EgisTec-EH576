#!/usr/bin/env python3
"""
Analyze captured EgisTec EH576 data
"""
import os
import binascii
from pathlib import Path

def analyze_file(filepath):
    """Analyze a binary file and provide insights"""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        
        size = len(data)
        print(f"\n📁 File: {filepath}")
        print(f"   Size: {size} bytes")
        
        if size == 0:
            print("   ❌ Empty file")
            return
        
        # Show first 32 bytes
        preview = data[:32]
        hex_preview = ' '.join(f'{b:02x}' for b in preview)
        print(f"   First 32 bytes: {hex_preview}")
        
        # Check for common patterns
        if data[:4] == b'EGIS':
            print("   ✅ Contains EGIS header")
        elif data[:4] == b'SIGE':
            print("   ✅ Contains SIGE header (reversed EGIS)")
        
        # Check for potential image data (non-zero, varied bytes)
        non_zero_bytes = sum(1 for b in data if b != 0)
        zero_ratio = (size - non_zero_bytes) / size
        
        if zero_ratio < 0.1:  # Less than 10% zeros
            print("   🖼️  HIGH LIKELIHOOD: Image data (low zero ratio)")
        elif zero_ratio < 0.5:  # Less than 50% zeros
            print("   📊 MEDIUM LIKELIHOOD: Sensor data")
        else:
            print("   📝 LOW LIKELIHOOD: Mostly zeros or status data")
        
        # Calculate entropy (rough measure of randomness/data complexity)
        byte_counts = [0] * 256
        for byte in data:
            byte_counts[byte] += 1
        
        entropy = 0
        for count in byte_counts:
            if count > 0:
                p = count / size
                entropy -= p * (p.bit_length() - 1)  # Simplified entropy calculation
        
        print(f"   Data complexity: {entropy:.2f} (higher = more complex)")
        
        # Look for repeating patterns
        if size > 100:
            # Check for large blocks of same data
            max_run = 1
            current_run = 1
            for i in range(1, min(size, 1000)):  # Check first 1000 bytes
                if data[i] == data[i-1]:
                    current_run += 1
                    max_run = max(max_run, current_run)
                else:
                    current_run = 1
            
            if max_run > 50:
                print(f"   ⚠️  Large run of same byte: {max_run} bytes")
        
        # Special analysis for potential fingerprint image
        if size > 5000:  # Large file likely to be image
            print("   🔍 LARGE FILE - Potential fingerprint image!")
            
            # EH575 image size was 103x52 = 5356 bytes
            if size == 5356:
                print("   🎯 EXACT EH575 IMAGE SIZE: 103x52 pixels")
            elif size > 5000:
                # Try to guess dimensions
                possible_dims = []
                for width in range(50, 200):
                    if size % width == 0:
                        height = size // width
                        if 30 <= height <= 100:  # Reasonable fingerprint dimensions
                            possible_dims.append((width, height))
                
                if possible_dims:
                    print("   📐 Possible image dimensions:")
                    for w, h in possible_dims[:5]:  # Show first 5 possibilities
                        print(f"      {w}x{h} pixels")
        
        return size, non_zero_bytes, entropy
        
    except Exception as e:
        print(f"   ❌ Error reading {filepath}: {e}")
        return 0, 0, 0

def main():
    print("🔍 EgisTec EH576 Capture Analysis")
    print("=" * 50)
    
    # Get all response files
    response_files = []
    for i in range(1, 18):
        filepath = f"post_init_packet_{i:02d}_response.bin"
        if os.path.exists(filepath):
            response_files.append(filepath)
    
    # Also check ep_0x82.bin
    if os.path.exists("ep_0x82.bin"):
        response_files.append("ep_0x82.bin")
    
    if not response_files:
        print("❌ No response files found!")
        return
    
    print(f"Found {len(response_files)} response files")
    
    # Analyze all files
    results = []
    for filepath in response_files:
        result = analyze_file(filepath)
        results.append((filepath, result))
    
    # Summary
    print(f"\n{'='*50}")
    print("📊 SUMMARY")
    print(f"{'='*50}")
    
    # Find largest files (likely images)
    large_files = [(f, r) for f, r in results if r[0] > 1000]
    large_files.sort(key=lambda x: x[1][0], reverse=True)
    
    if large_files:
        print("🖼️  LARGEST FILES (Potential Images):")
        for filepath, (size, non_zero, entropy) in large_files[:3]:
            print(f"   {filepath}: {size} bytes, {non_zero} non-zero bytes")
    
    # Find files with interesting data (low zero ratio)
    interesting_files = [(f, r) for f, r in results if r[0] > 0 and (r[1]/r[0]) > 0.5]
    if interesting_files:
        print("\n📋 FILES WITH SIGNIFICANT DATA:")
        for filepath, (size, non_zero, entropy) in interesting_files:
            zero_ratio = (size - non_zero) / size
            print(f"   {filepath}: {size} bytes, {100*(1-zero_ratio):.1f}% non-zero")
    
    # Recommendations
    print(f"\n{'='*50}")
    print("💡 RECOMMENDATIONS")
    print(f"{'='*50}")
    
    if large_files:
        largest_file = large_files[0][0]
        print(f"1. Analyze {largest_file} as potential fingerprint image")
        print("2. Try converting to image format (raw grayscale)")
        print("3. Test different dimensions if size doesn't match 103x52")
    
    print("4. The 'SIGE' responses show device communication is working")
    print("5. Command 6 appears to have triggered image capture successfully")

if __name__ == "__main__":
    main()
