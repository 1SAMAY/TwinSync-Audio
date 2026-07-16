# Privacy

TwinSync Audio is designed as a local Windows desktop application.

## Data The App Stores Locally

- Speaker selections
- Delay and volume settings
- Saved profiles
- Local diagnostic events
- Local backend logs

On Windows, app data and logs are stored under `%LOCALAPPDATA%\TwinSyncAudio` unless a developer overrides the path with `TWINSYNC_DATA_DIR` or `TWINSYNC_LOG_DIR`.

The portable package stores the same data under the adjacent `data` folder. Exported diagnostics omit device identifiers and names, usernames, audio, event messages, and full error text.

## Network And Telemetry

- TwinSync Audio does not require accounts.
- TwinSync Audio does not send telemetry.
- TwinSync Audio does not upload crash reports.
- TwinSync Audio does not process audio in the cloud.
- TwinSync Audio does not include ads.

The app may open the user's browser only when the user clicks a fixed About-page link.

TwinSync packages Microsoft Edge WebView2 Fixed Version Runtime for its local interface. Microsoft Defender SmartScreen is enabled in that runtime and may collect and send information to Microsoft as described in the [Microsoft Privacy Statement](https://aka.ms/privacy) and [Microsoft Edge Privacy Whitepaper](https://learn.microsoft.com/en-us/microsoft-edge/privacy-whitepaper#smartscreen). This is separate from TwinSync's application code, which does not add telemetry or upload audio.

## Audio

The app processes local Windows audio for routing and synchronization. It does not intentionally record, save, upload, or transmit full audio recordings.
