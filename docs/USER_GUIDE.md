# TwinSync Audio User Guide

## Start

1. Open TwinSync Audio.
2. Select a primary speaker.
3. Select a secondary speaker.
4. Press `Test A` and `Test B` to confirm both outputs.
5. Press `Start`.

## Sync Speakers

Use `Primary Delay` and `Secondary Delay` while audio is playing. Increase the delay on the speaker that sounds early. Save the result as a profile once the echo is gone.

## Calibration

TwinSync can submit test pulses to each speaker. Windows does not reliably expose the real acoustic Bluetooth latency of every speaker, so automatic measurement needs a measurement input. Without that input, TwinSync uses guided calibration and stores the delay you choose.

## Profiles

Profiles save the selected speaker pair, manual delay, estimated delay, volume, and audio format. Load a profile before pressing `Start` to restore a known pair.

## Diagnostics

The dashboard shows current software delay, drift estimate, buffer size, sample rate, bit depth, dropped frames, and connection health. Codec, battery, and signal strength appear only when the local audio stack exposes them.

