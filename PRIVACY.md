# Privacy

TwinSync Audio is designed as a local Windows desktop application.

## Data The App Stores Locally

- Speaker selections
- Delay and volume settings
- Saved profiles
- Local diagnostic events
- Local backend logs

On Windows, app data and logs are stored under `%LOCALAPPDATA%\TwinSyncAudio` unless a developer overrides the path with `TWINSYNC_DATA_DIR` or `TWINSYNC_LOG_DIR`.

## Network And Telemetry

- TwinSync Audio does not require accounts.
- TwinSync Audio does not send telemetry.
- TwinSync Audio does not upload crash reports.
- TwinSync Audio does not process audio in the cloud.
- TwinSync Audio does not include ads.

The app may open the user's browser only when the user clicks a fixed About-page link.

## Audio

The app processes local Windows audio for routing and synchronization. It does not intentionally record, save, upload, or transmit full audio recordings.
