# Changelog

## [0.2.0] - 2026-07-16

### Added

- Persistent live delay processors with crossfaded target changes.
- Smooth attack/hold/release noise gate and coordinated queue recovery.
- Endpoint clocks, queue latency, drift-correction, reconnect, stream, and worker diagnostics.
- Adaptive small-ratio resampling for normal drift correction.
- Microphone chirp calibration with repeated cross-correlation, outlier rejection, confidence, and guarded application.
- Shared audio-cycle cancellation and automatic reconnect with controlled backoff.
- Privacy-safe local diagnostics export.
- Cinematic CSS 3D UI, permanent playback HUD, four visual quality modes, and simple/developer diagnostics.
- Windows 10/11 x64 installer guard, optional desktop shortcut, portable-local data, offline WebView2 setup, and native startup error message.

### Fixed

- Manual trim on one speaker no longer contributes automatic delay to the other speaker.
- Live delay changes now update the active audio path.
- One failed output can no longer leave its sibling playing indefinitely.
- Frontend refreshes and actions are serialized; sliders are debounced.

### Changed

- Version and release tooling now target only `x86_64-pc-windows-msvc` production builds.
- Release reports distinguish automated simulation from unverified clean-machine and hardware behavior.

## [0.1.1] - 2026-07-11

### Fixed

- Prevented TwinSync from starting when the Windows default output is an unselected third device, which would leave the original Windows playback path audible outside TwinSync.
- Enforced selected-device validation before playback and profile restore.
- Stopped active playback before speaker-pair or profile changes to release stale output workers.
- Added routing diagnostics for selected output count, active output streams, playback workers, preview streams, active routing sessions, and per-device queue depth.
- Preserved explicit selected-device routing so connected but unselected devices are not opened by TwinSync.

## [0.1.0] - 2026-07-11

### Added

- Initial Windows desktop release packaging for TwinSync Audio.
- Local Tauri desktop shell for the React interface.
- Local Python backend launched by the desktop shell over JSON-lines IPC.
- Windows playback device selection for primary and secondary speakers.
- Manual per-speaker delay controls.
- Guided calibration pulse flow.
- Local SQLite profiles, settings, and event history.
- Bounded local backend log rotation.
- About Developer section with validated project and developer links.
- NSIS setup artifact, portable artifact, source archive, release notes, reports, and SHA-256 checksums.

### Known Limitations

- Synchronization quality depends on Bluetooth hardware, Windows drivers, codecs, speaker buffering, and local scheduling.
- Real Bluetooth playback, reconnect, sleep/resume, multi-monitor, and clean-machine install tests still require physical Windows test hardware.
- The project does not yet have an owner-selected open-source license.
