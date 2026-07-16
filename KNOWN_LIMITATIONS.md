# Known Limitations — v0.2.0

- Bluetooth emission time is controlled partly by adapter, Windows driver, codec, speaker firmware, and speaker buffering. Software clocks cannot prove acoustic alignment; use microphone calibration and manual trim.
- Default-loopback mode cannot safely re-render into its own Windows-default capture endpoint. That selected endpoint remains under Windows control and TwinSync identifies it in the UI. A dedicated virtual loopback source is required for two fully controlled output streams.
- SoundCard reaches native WASAPI through CFFI, while scheduling and DSP orchestration remain in the isolated Python sidecar. If hardware stress tests show the Python boundary misses production latency targets, the audio cycle should move to a dedicated Rust/C++ WASAPI service without changing UI/profile IPC.
- Device-change handling is event-like from the user's perspective but implemented with stream failure plus periodic endpoint validation because SoundCard does not expose the complete Windows notification surface.
- Automatic calibration measures relative arrival at one microphone position. Room reflections, automatic gain control, noise suppression, and microphone placement can lower confidence or bias results.
- Adaptive resampling is limited to ±1200 ppm. Larger discontinuities rebuild the routing cycle or use coordinated overflow recovery.
- The release binaries are unsigned; Windows SmartScreen may show an unknown-publisher warning.
- Installer and portable packages include Microsoft WebView2 Fixed Version Runtime 150.0.4078.65 x64. Unlike the evergreen runtime, this copy does not auto-update; each TwinSync release must refresh it for security fixes.
- The default current-user installer does not install to Program Files and avoids administrator permission. Program Files testing requires an explicitly authorized per-machine/copied test.
- Physical Bluetooth, sleep/resume, audio-service restart, mixed-DPI monitor, and clean-machine results must be recorded in `TEST_REPORT.md`; automated simulation does not prove those behaviors.
