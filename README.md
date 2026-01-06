# New Findings from scratch

Am currently implementing solution from scratch, using archived findings from https://github.com/Animeshz/EgisTec-EH575 as a basis for the EgisTec-EH576 fingerprint driver.

Archived previous efforts as I was overreliant on AI and got stuck with specific command sequences for fingerprint input and readings, currently reverse engineering windows driver using WireShark and Ghidra, and understanding how to find such sequences, what they actually mean, and how to use them to properly implement an efficient, safe, and usuable kernel driver for linux devices.

Current Status/Findings:

Original driver is a User-Mode Driver, which relies on kernel32.dll to DeviceIoControl to talk to the driver hardware, which is wrapped in a Vtable.

The main classes where findings are prevelant are in CRealTekDeviceCtrlForET576 and CET510SensorImp

## CRealTekDeviceCtrlForET576
- Handles the raw USB protocol (packets and sequences)

## CET510SensorImp
- Handles the different actions of fingerprint driver (Initialization, Calibration, and Scanning)

The Header of every packet includes "EGIS" (in hex form)

The packet structure is like so:

Header (4B) + CmD ID (1B) + Param1 (1B) + Param2 (1B)

# Protocol Mapping Discovery

Found all 3 major command sequences needed to operate fingerprint driver

## Write Register
- Cmd - 0x61
- Response is 7 Bytes

## Read Register
- Cmd - 0x62
- Response is 7 Bytes

## Get Image
- Cmd - 0x62
- Response is size of raw pixel data (currently finding to determine resolution of fingerprint images)

# Next Steps

Will be creating a python poke script that uses current findings to prove these sequences are corrrect and can properly read fingerprint images from driver utilizing them. 

After successfully doing so, will move on to implementation phase to write C driver through libfprint that will be a User Space driver.
