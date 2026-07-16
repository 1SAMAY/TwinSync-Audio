# TwinSync Audio v0.2.0 Hardware Test Checklist

Record Windows build, computer model, CPU architecture, audio adapter/driver, speaker models, microphone, tester, and date for each run. Do not check an item based only on compilation or simulation.

## Clean system

- [ ] Windows 10 x64 clean VM or computer with no Python, Node.js, npm, Rust, Cargo, or Visual Studio
- [ ] Windows 11 x64 clean VM or computer with no development tools
- [ ] Intel x64 computer
- [ ] AMD x64 computer
- [ ] Installer starts without administrator permission
- [ ] Installer rejects unsupported Windows/architecture with a clear message
- [ ] Missing WebView2 path is visible and does not silently download
- [ ] Fully offline installer installation and first startup

## Installer lifecycle

- [ ] Start Menu shortcut launches the app
- [ ] Desktop shortcut prompt works for Yes and No
- [ ] Install creates every required application file
- [ ] App launches from installed current-user path
- [ ] App launches after copying the installed folder under `Program Files`
- [ ] Profile survives reinstall
- [ ] Uninstall removes application files and shortcuts
- [ ] Uninstall preserves user profile data
- [ ] Reinstall succeeds after an active session has been closed

## Portable lifecycle

- [ ] Extract under a path containing spaces
- [ ] Extract under a path containing non-English characters
- [ ] `TwinSyncAudio.exe` runs directly without installation
- [ ] `data` receives settings, SQLite profile, diagnostics, and logs
- [ ] No system file, service, driver, or registry install is created
- [ ] Portable app works without internet access
- [ ] Portable app closes with no backend process left running

## Audio behavior

- [ ] Installation/startup discovers real outputs and inputs
- [ ] Test Primary plays only Primary
- [ ] Test Secondary plays only Secondary
- [ ] Start routes the source to the intended selected pair
- [ ] Unselected Windows-default third output is blocked
- [ ] Windows-controlled selected default is clearly identified
- [ ] Manual Primary trim changes only Primary
- [ ] Manual Secondary trim changes only Secondary
- [ ] Delay increases are smooth during playback
- [ ] Delay decreases are smooth during playback
- [ ] Primary and Secondary volume act independently where routing mode supports it
- [ ] Master volume and Emergency Stop work
- [ ] Stop closes capture/render streams
- [ ] Twenty repeated Start/Stop cycles leak no process, thread, or stream
- [ ] One-hour playback keeps bounded queue depth and acceptable drift

## Calibration

- [ ] Microphone selector lists the intended input
- [ ] Excessive background noise is rejected
- [ ] Chirps play separately on Primary and Secondary
- [ ] At least three measurements run
- [ ] Inconsistent measurements are removed
- [ ] Confidence score is displayed
- [ ] Low-confidence result is not applied
- [ ] Accepted result changes measured latency/automatic compensation
- [ ] Manual trim remains available after calibration

## Recovery

- [ ] Disconnect Primary Bluetooth device; Secondary does not continue indefinitely
- [ ] Reconnect Primary; profile, volume, delay, clocks, and audio restore
- [ ] Disconnect/reconnect Secondary
- [ ] Change Windows default output during playback
- [ ] Restart Windows Audio service
- [ ] Sleep and resume
- [ ] Windows shutdown while app is open
- [ ] Windows restart and app/profile reload
- [ ] No stale backend remains after normal close or failure

## Display and accessibility

- [ ] 100% DPI
- [ ] 125% DPI
- [ ] 150% DPI
- [ ] 200% DPI
- [ ] Single monitor
- [ ] Multiple monitors with equal DPI
- [ ] Multiple monitors with mixed DPI
- [ ] Windows light appearance
- [ ] Windows dark appearance
- [ ] Cinematic mode
- [ ] Balanced mode
- [ ] Performance mode
- [ ] Reduced Motion and Windows reduced-motion preference
- [ ] Minimize/restore pauses and resumes visual work without affecting audio
- [ ] Keyboard focus is visible and essential controls remain reachable

## Reports

- [ ] Exported diagnostics contain no device IDs, usernames, recordings, or full error text
- [ ] BUILD_REPORT.md matches the exact artifacts
- [ ] TEST_REPORT.md lists passed, failed, skipped, and unverified checks honestly
- [ ] SHA256SUMS.txt verifies every distributed file except itself
