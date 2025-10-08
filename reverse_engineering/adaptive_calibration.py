#!/usr/bin/env python3
"""
EgisTec EH576 - Adaptive Calibration Protocol
Finding optimal calibration parameters specific to EH576
"""
import usb.core
import usb.util
import time
import sys
from datetime import datetime

VENDOR = 0x1c7a
PRODUCT = 0x0576

def connect_device():
    dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
    if dev is None:
        print("❌ Device not found")
        return None
    
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError as e:
        print(f"❌ Permission error: {e}")
        return None
    
    intf = cfg[(0,0)]
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        dev.detach_kernel_driver(intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    
    print("✅ Device connected")
    return dev, intf

def send_and_receive(dev, cmd, expected_response_size=64, timeout=2000, description=""):
    """Send command and read response"""
    try:
        # Send command
        dev.write(0x01, bytes(cmd), timeout=timeout)
        cmd_str = ' '.join(f'{b:02x}' for b in cmd)
        print(f"📤 {description}: {cmd_str}")
        
        # Read response
        try:
            response = dev.read(0x82, expected_response_size, timeout=timeout)
            resp_str = ' '.join(f'{b:02x}' for b in response[:20])
            if len(response) > 20:
                resp_str += f"... ({len(response)} total bytes)"
            print(f"📥 Response: {resp_str}")
            
            return response
        except usb.core.USBError as e:
            if 'timeout' not in str(e).lower():
                print(f"❌ Read error: {e}")
            return None
            
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def analyze_capture_quality(data):
    """Enhanced analysis of captured data"""
    if not data or len(data) < 100:
        return 0, "No data"
    
    non_zero_bytes = sum(1 for b in data if b != 0)
    total_bytes = len(data)
    percentage = (non_zero_bytes / total_bytes) * 100
    
    # Calculate entropy (simplified)
    unique_values = len(set(data))
    entropy = unique_values / 256
    
    # Calculate variance for fingerprint detection
    mean = sum(data) / len(data)
    variance = sum((b - mean) ** 2 for b in data) / len(data)
    
    quality_score = percentage * entropy * (variance / 100)
    
    if percentage > 30 and entropy > 0.4:
        status = "EXCELLENT"
    elif percentage > 15 and entropy > 0.2:
        status = "GOOD"
    elif percentage > 5 and entropy > 0.1:
        status = "FAIR"
    else:
        status = "POOR"
    
    return quality_score, f"{status} ({percentage:.1f}% non-zero, entropy: {entropy:.2f}, variance: {variance:.1f}, score: {quality_score:.1f})"

def test_calibration_variant(dev, variant_name, pre_commands, capture_command, capture_size):
    """Test a specific calibration variant"""
    print(f"\n🧪 Testing {variant_name}")
    print("=" * 50)
    
    # Execute pre-commands
    for i, cmd in enumerate(pre_commands):
        response = send_and_receive(dev, cmd, timeout=3000, description=f"Pre-cmd {i+1}")
        time.sleep(0.2)
    
    print(f"\n🎯 Executing capture command")
    print("👆 PLACE YOUR FINGER ON THE SENSOR NOW!")
    time.sleep(2)  # Give time to place finger
    
    # Execute capture
    response = send_and_receive(dev, capture_command, capture_size, timeout=5000, description="CAPTURE")
    
    if response:
        score, quality = analyze_capture_quality(response)
        print(f"🔍 Quality: {quality}")
        
        if score > 10:  # Save good captures
            filename = f"{variant_name.lower().replace(' ', '_')}_{datetime.now().strftime('%H%M%S')}.bin"
            with open(filename, 'wb') as f:
                f.write(response)
            print(f"💾 Saved to {filename}")
        
        return score, response
    
    return 0, None

def run_adaptive_calibration(dev):
    """Run multiple calibration variants to find the best one"""
    print("\n🔬 EgisTec EH576 - Adaptive Calibration")
    print("Testing multiple calibration approaches...")
    print("=" * 60)
    
    best_score = 0
    best_variant = None
    best_data = None
    
    # Variant 1: Your original working sequence (adapted)
    variant1_pre = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x09, 0x0b, 0x83, 0x24, 0x00, 0x44, 0x0f, 0x08, 0x20, 0x20, 0x01, 0x05, 0x12],
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06],
    ]
    score1, data1 = test_calibration_variant(dev, "EH576 Original", variant1_pre, 
                                            [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 6000)
    
    if score1 > best_score:
        best_score, best_variant, best_data = score1, "EH576 Original", data1
    
    time.sleep(1)
    
    # Variant 2: EH575 key calibration commands only
    variant2_pre = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00],  # EH575 style
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00],
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfc],  # Critical calibration
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06],  # Config
        [0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec],  # Background capture
    ]
    score2, data2 = test_calibration_variant(dev, "EH575 Minimal", variant2_pre,
                                            [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 6000)
    
    if score2 > best_score:
        best_score, best_variant, best_data = score2, "EH575 Minimal", data2
    
    time.sleep(1)
    
    # Variant 3: Hybrid approach with different parameters
    variant3_pre = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],  # EH576 style init
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd],  # EH575 calibration variant
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x50, 0x03],  # Sensor setup
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x50, 0x03],
        [0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec],  # Background capture
    ]
    score3, data3 = test_calibration_variant(dev, "Hybrid EH575/576", variant3_pre,
                                            [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 6000)
    
    if score3 > best_score:
        best_score, best_variant, best_data = score3, "Hybrid EH575/576", data3
    
    time.sleep(1)
    
    # Variant 4: Timing-sensitive approach
    variant4_pre = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc],
    ]
    
    print(f"\n🧪 Testing Timing Sensitive")
    print("=" * 50)
    
    # Execute with longer delays
    for i, cmd in enumerate(variant4_pre):
        response = send_and_receive(dev, cmd, timeout=3000, description=f"Timing-cmd {i+1}")
        time.sleep(1.0)  # Longer delay
    
    # Multiple background captures
    print("🔄 Multiple background captures...")
    for i in range(3):
        bg_response = send_and_receive(dev, [0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], 6000, 
                                     timeout=5000, description=f"Background {i+1}")
        time.sleep(0.5)
    
    print("👆 PLACE YOUR FINGER ON THE SENSOR NOW!")
    time.sleep(2)
    
    response = send_and_receive(dev, [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 6000, 
                               timeout=5000, description="CAPTURE")
    
    if response:
        score4, quality = analyze_capture_quality(response)
        print(f"🔍 Quality: {quality}")
        
        if score4 > 10:
            filename = f"timing_sensitive_{datetime.now().strftime('%H%M%S')}.bin"
            with open(filename, 'wb') as f:
                f.write(response)
            print(f"💾 Saved to {filename}")
        
        if score4 > best_score:
            best_score, best_variant, best_data = score4, "Timing Sensitive", response
    
    # Report results
    print(f"\n📊 CALIBRATION RESULTS")
    print("=" * 50)
    print(f"Best approach: {best_variant}")
    print(f"Best score: {best_score:.1f}")
    
    if best_score > 20:
        print("🎉 Found good calibration approach!")
        return True, best_variant
    elif best_score > 10:
        print("📈 Found decent calibration approach - may need refinement")
        return True, best_variant
    else:
        print("⚠️  All approaches still show poor quality - need further investigation")
        return False, best_variant

def test_parameter_variations(dev):
    """Test variations in the capture command parameters"""
    print(f"\n🔬 Testing Parameter Variations")
    print("=" * 50)
    
    # Base setup (your working commands)
    base_setup = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc],
    ]
    
    # Execute base setup
    for cmd in base_setup:
        send_and_receive(dev, cmd, timeout=3000)
        time.sleep(0.2)
    
    # Test different capture command variations
    capture_variants = [
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "Original (0xec)"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xfc], "Variant fc"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0x00], "Variant 00"),
        ([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background style"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x40, 0xec], "Different param"),
    ]
    
    best_param_score = 0
    best_param = None
    
    for cmd, name in capture_variants:
        print(f"\n🧪 Testing {name}")
        print("👆 PLACE YOUR FINGER ON THE SENSOR NOW!")
        time.sleep(1.5)
        
        response = send_and_receive(dev, cmd, 6000, timeout=5000, description=name)
        
        if response:
            score, quality = analyze_capture_quality(response)
            print(f"🔍 Quality: {quality}")
            
            if score > best_param_score:
                best_param_score = score
                best_param = name
                
                filename = f"param_test_{name.lower().replace(' ', '_')}_{datetime.now().strftime('%H%M%S')}.bin"
                with open(filename, 'wb') as f:
                    f.write(response)
                print(f"💾 Best so far - saved to {filename}")
        
        time.sleep(1)
    
    print(f"\n📊 Best parameter variation: {best_param} (score: {best_param_score:.1f})")
    return best_param_score > 15

def main():
    print("🔬 EgisTec EH576 - Adaptive Calibration Protocol")
    print("Finding optimal calibration for your specific device")
    print("=" * 65)
    
    result = connect_device()
    if result is None:
        return
    
    dev, intf = result
    
    try:
        # Run adaptive calibration tests
        success, best_approach = run_adaptive_calibration(dev)
        
        if success:
            print(f"\n✅ Best approach found: {best_approach}")
            
            # Test parameter variations
            print(f"\n🔧 Fine-tuning parameters...")
            param_success = test_parameter_variations(dev)
            
            if param_success:
                print(f"\n🎊 SUCCESS! Found optimal calibration for EH576!")
            else:
                print(f"\n📈 Partial success - calibration improved but may need more work")
        else:
            print(f"\n❌ Unable to find good calibration - device may need different approach")
            print("Consider checking:")
            print("- Finger placement and pressure")
            print("- Sensor cleanliness") 
            print("- USB connection stability")
            print("- Device-specific initialization sequence")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        try:
            dev.attach_kernel_driver(intf.bInterfaceNumber)
        except:
            pass

if __name__ == "__main__":
    main()
