import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useDisplayPerformance } from "./useDisplayPerformance";

type AudioDevice = {
  id: string;
  name: string;
  is_output: boolean;
  is_input: boolean;
  connection_type: string;
  is_default: boolean;
  channels: number | null;
  codec: string | null;
  battery_percent: number | null;
  current_latency_ms: number | null;
  signal_strength_percent: number | null;
  status: string;
};

type Status = {
  selection: { primary_id: string | null; secondary_id: string | null };
  delay: {
    primary_manual_ms: number;
    secondary_manual_ms: number;
    primary_estimated_ms: number;
    secondary_estimated_ms: number;
  };
  volume: { master: number; primary: number; secondary: number; muted: boolean; balance: number };
  audio_mode: { name: string; sample_rate: number; bit_depth: number; channels: number; buffer_ms: number };
  effective_delay: { primary_ms: number; secondary_ms: number };
  metrics: {
    playback_state: string;
    current_delay_primary_ms: number;
    current_delay_secondary_ms: number;
    estimated_drift_ms: number;
    buffer_size_ms: number;
    dropped_frames: number;
    sample_rate: number;
    bit_depth: number;
    cpu_usage_percent: number | null;
    connection_health: string;
    last_error: string | null;
  };
  events: EventItem[];
};

type EventItem = {
  id: number;
  category: string;
  message: string;
  created_at: string;
};

type Profile = {
  id: number;
  name: string;
  updated_at?: string;
};

async function backendRequest<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return invoke<T>("backend_request", { method, params });
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const blankStatus: Status = {
  selection: { primary_id: null, secondary_id: null },
  delay: {
    primary_manual_ms: 0,
    secondary_manual_ms: 0,
    primary_estimated_ms: 0,
    secondary_estimated_ms: 0
  },
  volume: { master: 1, primary: 1, secondary: 1, muted: false, balance: 0 },
  audio_mode: { name: "Balanced", sample_rate: 48000, bit_depth: 24, channels: 2, buffer_ms: 60 },
  effective_delay: { primary_ms: 0, secondary_ms: 0 },
  metrics: {
    playback_state: "stopped",
    current_delay_primary_ms: 0,
    current_delay_secondary_ms: 0,
    estimated_drift_ms: 0,
    buffer_size_ms: 0,
    dropped_frames: 0,
    sample_rate: 48000,
    bit_depth: 24,
    cpu_usage_percent: null,
    connection_health: "idle",
    last_error: null
  },
  events: []
};

const APP_VERSION = "0.1.1";
const TRUSTED_LINKS = new Set([
  "https://github.com/1SAMAY",
  "https://github.com/1SAMAY/TwinSync-Audio",
  "https://samay-dev-portfolio.vercel.app/",
  "https://www.linkedin.com/in/samay-dudhrejiya",
  "mailto:samay4932@gmail.com"
]);

function openTrustedLink(url: string) {
  if (!TRUSTED_LINKS.has(url)) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

export default function App() {
  useDisplayPerformance();
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [status, setStatus] = useState<Status>(blankStatus);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string>("");
  const [profileName, setProfileName] = useState("Default Pair");
  const lastDevicesJson = useRef("");
  const lastStatusJson = useRef("");
  const lastProfilesJson = useRef("");

  const outputDevices = useMemo(() => devices.filter((device) => device.is_output), [devices]);
  const primaryName = outputDevices.find((device) => device.id === status.selection.primary_id)?.name ?? "Not selected";
  const secondaryName = outputDevices.find((device) => device.id === status.selection.secondary_id)?.name ?? "Not selected";
  const isPlaying = status.metrics.playback_state === "playing" || status.metrics.playback_state === "starting";

  const setIfChanged = useCallback(<T,>(
    value: T,
    previousJson: React.MutableRefObject<string>,
    setter: React.Dispatch<React.SetStateAction<T>>
  ) => {
    const nextJson = JSON.stringify(value);
    if (nextJson !== previousJson.current) {
      previousJson.current = nextJson;
      setter(value);
    }
  }, []);

  const refresh = useCallback(async () => {
    const errors: string[] = [];
    try {
      setIfChanged(await backendRequest<AudioDevice[]>("devices"), lastDevicesJson, setDevices);
    } catch (err) {
      errors.push(errorMessage(err));
    }
    try {
      setIfChanged(await backendRequest<Status>("status"), lastStatusJson, setStatus);
    } catch (err) {
      errors.push(errorMessage(err));
    }
    try {
      setIfChanged(await backendRequest<Profile[]>("profiles"), lastProfilesJson, setProfiles);
    } catch (err) {
      errors.push(errorMessage(err));
    }
    setError((current) => {
      const next = errors.join(" ");
      return current === next ? current : next;
    });
  }, [setIfChanged]);

  useEffect(() => {
    let timer = 0;
    const startPolling = () => {
      window.clearInterval(timer);
      if (document.visibilityState === "hidden") return;
      timer = window.setInterval(refresh, 2500);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        window.clearInterval(timer);
        return;
      }
      refresh();
      startPolling();
    };

    refresh();
    startPolling();
    document.addEventListener("visibilitychange", onVisibilityChange, { passive: true });
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refresh]);

  const selectSpeakers = useCallback(async (primary_id: string | null, secondary_id: string | null) => {
    const nextPrimary = primary_id || null;
    const nextSecondary = secondary_id || null;
    if (nextPrimary && nextSecondary && nextPrimary === nextSecondary) {
      setError("Primary and secondary speakers must be different devices.");
      return;
    }
    setStatus(await backendRequest<Status>("select_speakers", { primary_id: nextPrimary, secondary_id: nextSecondary }));
    await refresh();
  }, [refresh]);

  const setDelay = useCallback(async (which: "primary_manual_ms" | "secondary_manual_ms", value: number) => {
    setStatus(await backendRequest<Status>("set_delay", { [which]: value }));
  }, []);

  const setVolume = useCallback(async (which: "master" | "primary" | "secondary", value: number) => {
    setStatus(await backendRequest<Status>("set_volume", { [which]: value / 100 }));
  }, []);

  const start = useCallback(async () => {
    try {
      setStatus(await backendRequest<Status>("start"));
      setError("");
    } catch (err) {
      setError(errorMessage(err));
      await refresh();
    }
  }, [refresh]);

  const stop = useCallback(async () => {
    setStatus(await backendRequest<Status>("stop"));
  }, []);

  const testSound = useCallback(async (device_id: string | null) => {
    if (!device_id) return;
    setStatus(await backendRequest<Status>("test_sound", { device_id }));
  }, []);

  const calibrate = useCallback(async () => {
    const result = await backendRequest<{ message: string }>("calibrate");
    setError(result.message);
    await refresh();
  }, [refresh]);

  const saveProfile = useCallback(async () => {
    await backendRequest("save_profile", { name: profileName });
    await refresh();
  }, [profileName, refresh]);

  const loadProfile = useCallback(async (profile_id: number) => {
    setStatus(await backendRequest<Status>("load_profile", { profile_id }));
    await refresh();
  }, [refresh]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">TwinSync Audio</p>
          <h1>Dual Speaker Sync</h1>
        </div>
        <div className={`state-pill ${status.metrics.playback_state}`}>
          <span />
          {status.metrics.playback_state}
        </div>
      </header>

      {error && <div className="notice">{error}</div>}

      <section className="hero-grid">
        <div className="panel status-panel">
          <div className="pair">
            <div>
              <p>Primary</p>
              <strong>{primaryName}</strong>
            </div>
            <div className="sync-orb">{Math.round(status.effective_delay.primary_ms)} ms</div>
          </div>
          <div className="pair">
            <div>
              <p>Secondary</p>
              <strong>{secondaryName}</strong>
            </div>
            <div className="sync-orb alt">{Math.round(status.effective_delay.secondary_ms)} ms</div>
          </div>
          <div className="controls">
            <button onClick={isPlaying ? stop : start}>{isPlaying ? "Stop" : "Start"}</button>
            <button onClick={calibrate}>Calibrate</button>
            <button onClick={refresh}>Refresh</button>
          </div>
        </div>

        <div className="panel metrics-panel">
          <Metric label="Drift" value={`${status.metrics.estimated_drift_ms.toFixed(2)} ms`} />
          <Metric label="Buffer" value={`${status.audio_mode.buffer_ms} ms`} />
          <Metric label="Sample Rate" value={`${status.audio_mode.sample_rate / 1000} kHz`} />
          <Metric label="Bit Depth" value={`${status.audio_mode.bit_depth}-bit`} />
          <Metric label="Dropped Frames" value={String(status.metrics.dropped_frames)} />
          <Metric label="Health" value={status.metrics.connection_health} />
        </div>
      </section>

      <section className="content-grid">
        <div className="panel">
          <h2>Device Manager</h2>
          <div className="selectors">
            <label>
              Primary Speaker
              <select
                value={status.selection.primary_id ?? ""}
                onChange={(event) => selectSpeakers(event.target.value, status.selection.secondary_id)}
              >
                <option value="">Select</option>
                {outputDevices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Secondary Speaker
              <select
                value={status.selection.secondary_id ?? ""}
                onChange={(event) => selectSpeakers(status.selection.primary_id, event.target.value)}
              >
                <option value="">Select</option>
                {outputDevices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="controls compact">
            <button onClick={() => testSound(status.selection.primary_id)}>Test A</button>
            <button onClick={() => testSound(status.selection.secondary_id)}>Test B</button>
            <button onClick={() => selectSpeakers(status.selection.secondary_id, status.selection.primary_id)}>Swap</button>
          </div>
          <div className="device-list">
            {outputDevices.length === 0 && (
              <article className="empty-row">
                <strong>No playback devices returned</strong>
                <span>Connect speakers in Windows Sound settings, then press Refresh.</span>
              </article>
            )}
            {outputDevices.map((device) => (
              <DeviceRow key={device.id} device={device} />
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Synchronization</h2>
          <DelayControl
            label="Primary Delay"
            value={status.delay.primary_manual_ms}
            onChange={(value) => setDelay("primary_manual_ms", value)}
          />
          <DelayControl
            label="Secondary Delay"
            value={status.delay.secondary_manual_ms}
            onChange={(value) => setDelay("secondary_manual_ms", value)}
          />
          <VolumeControl label="Master Volume" value={status.volume.master * 100} onChange={(value) => setVolume("master", value)} />
          <VolumeControl label="Primary Volume" value={status.volume.primary * 100} onChange={(value) => setVolume("primary", value)} />
          <VolumeControl label="Secondary Volume" value={status.volume.secondary * 100} onChange={(value) => setVolume("secondary", value)} />
        </div>

        <div className="panel">
          <h2>Profiles</h2>
          <div className="profile-save">
            <input value={profileName} onChange={(event) => setProfileName(event.target.value)} />
            <button onClick={saveProfile}>Save</button>
          </div>
          <div className="profile-list">
            {profiles.map((profile) => (
              <ProfileButton key={profile.id} profile={profile} onLoad={loadProfile} />
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Event Log</h2>
          <div className="event-list">
            {status.events.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </div>
        </div>

        <div className="panel about-panel">
          <h2>About TwinSync Audio</h2>
          <div className="about-copy">
            <strong>TwinSync Audio</strong>
            <span>Version {APP_VERSION}</span>
            <p>TwinSync Audio allows Windows users to route and synchronize audio across compatible speaker devices.</p>
            <span>Developed by SAMAY DUDHREJIYA</span>
          </div>
          <div className="link-grid">
            <button onClick={() => openTrustedLink("https://github.com/1SAMAY")}>GitHub</button>
            <button onClick={() => openTrustedLink("https://github.com/1SAMAY/TwinSync-Audio")}>Repository</button>
            <button onClick={() => openTrustedLink("https://samay-dev-portfolio.vercel.app/")}>Portfolio</button>
            <button onClick={() => openTrustedLink("https://www.linkedin.com/in/samay-dudhrejiya")}>LinkedIn</button>
            <button onClick={() => openTrustedLink("mailto:samay4932@gmail.com")}>Contact Email</button>
          </div>
          <p className="copyright">Copyright (c) 2026 SAMAY DUDHREJIYA</p>
        </div>
      </section>
    </main>
  );
}

const Metric = memo(function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
});

const DelayControl = memo(function DelayControl({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="range-control">
      <span>{label}</span>
      <input min={0} max={500} step={1} type="range" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <input min={0} max={500} step={1} type="number" value={Math.round(value)} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
});

const VolumeControl = memo(function VolumeControl({
  label,
  value,
  onChange
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="range-control">
      <span>{label}</span>
      <input min={0} max={100} step={1} type="range" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <input min={0} max={100} step={1} type="number" value={Math.round(value)} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
});

const DeviceRow = memo(function DeviceRow({ device }: { device: AudioDevice }) {
  return (
    <article className="device-row">
      <div>
        <strong>{device.name}</strong>
        <span>{device.connection_type}</span>
      </div>
      <div>
        <span>{device.codec ?? "Codec unavailable"}</span>
        <span>{device.battery_percent === null ? "Battery unavailable" : `${device.battery_percent}%`}</span>
      </div>
    </article>
  );
});

const ProfileButton = memo(function ProfileButton({
  profile,
  onLoad
}: {
  profile: Profile;
  onLoad: (profileId: number) => void;
}) {
  const handleClick = useCallback(() => onLoad(profile.id), [onLoad, profile.id]);
  return <button onClick={handleClick}>{profile.name}</button>;
});

const EventRow = memo(function EventRow({ event }: { event: EventItem }) {
  return (
    <article>
      <span>{event.category}</span>
      <strong>{event.message}</strong>
      <small>{event.created_at}</small>
    </article>
  );
});
