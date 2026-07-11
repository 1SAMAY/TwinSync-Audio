# Changelog

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
