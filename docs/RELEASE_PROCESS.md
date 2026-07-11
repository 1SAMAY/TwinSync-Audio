# Release Process

1. Confirm the version is correct in `pyproject.toml`, `frontend/package.json`, `frontend/src-tauri/Cargo.toml`, and `frontend/src-tauri/tauri.conf.json`.
2. Update `CHANGELOG.md`.
3. Run:

```powershell
.\installer\build_windows.ps1
```

4. Review `release\v0.1.1\BUILD_REPORT.md`.
5. Review `release\v0.1.1\TEST_REPORT.md`.
6. Install `TwinSyncAudio-Setup-v0.1.1.exe` on a clean Windows test machine.
7. Test real Bluetooth/audio playback, synchronization, profile save/load, shutdown, uninstall, and reinstall.
8. Create and push tag `v0.1.1` only after the manual checks pass.
9. Create a GitHub release titled `TwinSync Audio v0.1.1`.
10. Attach the setup exe, portable zip, source zip, and `SHA256SUMS.txt`.

Do not publish if secrets, private logs, private databases, or placeholder links are present.
