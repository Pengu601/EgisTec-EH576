#!/usr/bin/env python3
import usb.core
import usb.util

VENDOR = 0x1c7a
PRODUCT = 0x0576

def analyze_device():
    dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
    if dev is None:
        print("Device not found")
        return
    
    print(f"Device: {dev}")
    print(f"Manufacturer: {dev.manufacturer}")
    print(f"Product: {dev.product}")
    print(f"Serial: {dev.serial_number}")
    print()
    
    cfg = dev.get_active_configuration()
    print(f"Configuration {cfg.bConfigurationValue}:")
    
    for intf in cfg:
        print(f"  Interface {intf.bInterfaceNumber}:")
        print(f"    Class: {intf.bInterfaceClass}")
        print(f"    Subclass: {intf.bInterfaceSubClass}")
        print(f"    Protocol: {intf.bInterfaceProtocol}")
        
        for ep in intf:
            print(f"    Endpoint {ep.bEndpointAddress:#04x}:")
            print(f"      Type: {usb.util.endpoint_type(ep.bmAttributes)}")
            print(f"      Direction: {'IN' if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else 'OUT'}")
            print(f"      Max packet size: {ep.wMaxPacketSize}")
            print(f"      Interval: {ep.bInterval}")

if __name__ == "__main__":
    analyze_device()
