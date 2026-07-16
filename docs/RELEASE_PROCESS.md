# Release Process

1. Confirm `0.2.0` in Python, npm, Cargo, Tauri, and UI metadata.
2. Run `installer\build_windows.ps1` on Windows x64.
3. Verify `SHA256SUMS.txt` and inspect `BUILD_REPORT.md` and `TEST_REPORT.md`.
4. Run every applicable item in `docs\HARDWARE_TEST_CHECKLIST.md` on a clean Windows 10 or Windows 11 x64 system without developer tools.
5. Record exact pass/fail/skip results in `TEST_REPORT.md`, then regenerate its checksum.
6. Do not publish if installation, startup, routing, storage, close, uninstall, reinstall, portable execution, or offline behavior fails.
7. Tag `v0.2.0` only after the clean-machine and hardware matrix is accepted by the release owner.
8. Attach all seven required release files to the GitHub release.

Do not publish secrets, logs, databases, device identifiers, private diagnostics, or a claim that was only simulated.
