# EgisTec EH576 Fingerprint Scanner

Reverse engineering project for the EgisTec EH576 USB fingerprint scanner to enable Linux support.

## Quick Status

🔄 **ACTIVE DEVELOPMENT** - Protocol working, working on calibration

- ✅ **USB Communication**: Established
- ✅ **Protocol Discovery**: EgisTec format decoded  
- ✅ **Device Commands**: Initialization and capture commands working
- 🔄 **Image Capture**: Getting responses but need calibration for quality data
- ❌ **Calibration**: In progress - main blocker for usable fingerprints

## Device Info
- **VendorID**: 0x1c7a
- **ProductID**: 0x0576  
- **Protocol**: EgisTec proprietary (EGIS/SIGE headers)
- **Status**: Device communicates, captures data, needs calibration sequence

## Working Commands

**Command 6** (Image Capture): `[0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]` ⭐  
✅ Device responds with 2000+ byte data blocks

## Current Issue
Getting mostly zero bytes in fingerprint captures despite successful device communication. Research indicates sensor requires calibration sequence before imaging (based on EH575 driver analysis).

## Files

### Research Scripts
- `reverse_engineering/polling.py` - Main research script
- `reverse_engineering/capture_fingerprint.py` - Targeted capture using Command 6
- `reverse_engineering/advanced_capture.py` - Multiple calibration strategies

### Research Data  
- `EgisTec-EH575/` - Related EH575 driver research and USB traces
- `FINDINGS_SUMMARY.md` - Detailed technical findings and next steps

### System Info
- `device_node_info.txt` - USB device enumeration
- `fprintd_version_info.txt` - Fingerprint service info  
- `kernel_info.txt` - Kernel driver info

## Setup

1. **USB Permissions**:
   ```bash
   sudo cp 99-egistec.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   ```

2. **Test Communication**:
   ```bash
   cd reverse_engineering
   python3 capture_fingerprint.py
   ```

## Next Steps

1. **Implement calibration sequence** from EH575 research
2. **Test advanced capture strategies** with sensor baseline
3. **Convert binary data to images** once good captures obtained  
4. **Integrate with libfprint** for Linux authentication

See `FINDINGS_SUMMARY.md` for detailed technical analysis and actionable next steps.

---
**Progress**: 70% complete - Protocol working, calibration needed for quality capture