# New Findings from scratch

Am currently implementing solution from scratch, using archived findings from https://github.com/Animeshz/EgisTec-EH575 as a basis for the EgisTec-EH576 fingerprint driver.

Archived previous efforts as I was overreliant on AI and got stuck with specific command sequences for fingerprint input and readings, currently reverse engineering windows driver using WireShark and Ghidra, and understanding how to find such sequences, what they actually mean, and how to use them to properly implement an efficient, safe, and usuable kernel driver for linux devices.

Current Status/Findings:

Went through a whole TLS encryption phase which eventually found out wasn't even necessary as it was implemented software side instead of directly on the sensor. 

Finally got fingerprints to be dumped from the sensor using the commands and init/polling sequences. 

## CRealTekDeviceCtrlForET576
- Handles the raw USB protocol (packets and sequences)

## CET510SensorImp
- Handles the different actions of fingerprint driver (Initialization, Calibration, and Scanning)

The Header of every packet includes "EGIS" (in hex form)

The packet structure is like so:

Header (4B) + CmD ID (1B) + Param1 (1B) + Param2 (1B)

# Protocol Mapping Discovery

Found major command sequences needed to operate fingerprint driver

## Read/Execute Register
- Cmd - 0x60
- Read a register or trigger basic state change

## Write Register
- Cmd - 0x61
- Writes a specific hex value into single hardware register, Response is 7 Bytes

## Burst Read Register
- Cmd - 0x62
- Requests sensor to return current values of multiple registers

## Get Image
- Cmd - 0x62
- Response is size of raw pixel data (currently finding to determine resolution of fingerprint images)

## Burst Write
- Cmd - 0x63
- Pushes multi-byte config data into sensor. Used mainly for for init sequence.

# Specific Commands

## The Poll Command
- 45 47 49 53 60 00 00
- sent in a continuous loop to ask sensor for status update

## Image Fetch Command
- 45 47 49 53 64 0f 96
- 0x64 tells sensor to dump image buffer
- 0f 96 = 3990 bytes, which equates to image size (70x57 pixels)

# Variance Math
The way this sensor works is that when reading for finger, it is always active (whether finger is present or not), and it doesn't
have some response it sends when it detects a finger. This was designed to detect fingers all from the software side.

We can do this using population variance (statistics), which measures how spread out a set of numbers is from the mean. Essentially, each byte from the 3990 represents a voltage reading from 0 (black) to 255 (white). When finger is not on the sensor, the electrical capactiance is basically uniform, which means every single pixel will have a very similar value (let's say 40). Since the average is 40, and almost every pixel will be 40, the difference between each pixel and the mean is 0. Thus, the variance is close to 0.

Now, if a finger is present, the ridges and valleys of the finger will give both strong and lighter electrical connections at once, where some pixels read dark (like 10) and others lighter (90). The average could be 40 still, but now half are 30 points below and half are 60 points above the average. Thus, the variance spikes massively, going anywhere from 15 to 30.

This is very good as it only cares about contrast, so any environmental impact (like heat) will not affect its measurements.
# Next Steps

## The issue
If I were to integrate this implementation with the current fprintd algorithm it uses (Bozorth3), the accuracy for enrolling and getting matches for the fingerprints will be extremely bad and inconsistent, or just not secure. This is because this algorithm used natively is very old and built for bigger image outputs, as it checks for minutiae. 

## Solution

The solution is to essentially build a custom algorithm which i can override the native fprintd algorithm with. 

### Work to do

I have to start by gathering a bunch of fingeprints, for different fingers. Then I build an image preprocessing pipeline to clean all the fingerprints to allow for a more distinct and clear constrast to easily see the fingerprints, which makes the matching significantly faster and more accurate. 

I will then build the actual matching logic. Will either go the phase correlation route or the siamese Neural Network route, depending on feasibility and which one i think is cooler lol (leaning towards the computer vision route, seems interesting).

