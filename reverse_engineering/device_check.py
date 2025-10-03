#!/usr/bin/env python3
import usb.core
import usb.util
import sys

VENDOR = 0x1c7a
PRODUCT = 0x0576

print("Searching for EgisTec device...")
dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)

if dev is None:
    print("❌ Device not found!")
    print("Make sure the fingerprint scanner is connected.")
    sys.exit(1)

print(f"✅ Device found!")
print(f"   Bus: {dev.bus}")
print(f"   Address: {dev.address}")
print(f"   Vendor ID: 0x{dev.idVendor:04x}")
print(f"   Product ID: 0x{dev.idProduct:04x}")

try:
    print(f"   Manufacturer: {dev.manufacturer}")
    print(f"   Product: {dev.product}")
    print(f"   Serial: {dev.serial_number}")
except:
    print("   (Could not read device strings)")

try:
    cfg = dev.get_active_configuration()
    print(f"✅ Configuration access: OK")
    
    print(f"Configuration details:")
    print(f"   Configuration value: {cfg.bConfigurationValue}")
    print(f"   Number of interfaces: {len(cfg.interfaces())}")
    
    for intf in cfg:
        print(f"   Interface {intf.bInterfaceNumber}:")
        print(f"      Class: 0x{intf.bInterfaceClass:02x}")
        print(f"      Subclass: 0x{intf.bInterfaceSubClass:02x}")
        print(f"      Protocol: 0x{intf.bInterfaceProtocol:02x}")
        print(f"      Endpoints:")
        
        for ep in intf:
            direction = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
            ep_type = ["CONTROL", "ISOCHRONOUS", "BULK", "INTERRUPT"][usb.util.endpoint_type(ep.bmAttributes)]
            print(f"         0x{ep.bEndpointAddress:02x} ({direction}, {ep_type}, max {ep.wMaxPacketSize} bytes)")

except usb.core.USBError as e:
    print(f"❌ Configuration access failed: {e}")
    print("This usually means permission issues.")
    print("Try running with sudo or check udev rules.")
    sys.exit(1)

print("\n✅ Device is accessible and ready for communication!")
