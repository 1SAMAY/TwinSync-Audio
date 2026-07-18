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

type Metrics = {
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
  selected_output_count: number;
  active_output_stream_count: number;
  active_playback_worker_count: number;
  preview_stream_count: number;
  routing_session_count: number;
  queue_depths: Record<string, number>;
  queue_latency_ms: Record<string, number>;
  endpoint_clock_frames: Record<string, number>;
  endpoint_clock_position_ms: Record<string, number>;
  relative_clock_error_ms: number;
  drift_correction_ppm: Record<string, number>;
  capture_latency_ms: number;
  render_latency_ms: Record<string, number>;
  automatic_compensation_primary_ms: number;
  automatic_compensation_secondary_ms: number;
  acoustic_offset_ms: number | null;
  calibration_confidence: number | null;
  buffer_underruns: number;
  buffer_overruns: number;
  reconnect_attempts: number;
  reconnect_state: string;
  routing_mode: string;
  uncontrolled_output_name: string | null;
  routing_warning: string | null;
};

type Status = {
  selection: { primary_id: string | null; secondary_id: string | null };
  source_id: string | null;
  delay: {
    primary_manual_ms: number;
    secondary_manual_ms: number;
    primary_estimated_ms: number;
    secondary_estimated_ms: number;
  };
  volume: { master: number; primary: number; secondary: number; muted: boolean; balance: number };
  audio_mode: { name: string; sample_rate: number; bit_depth: number; channels: number; buffer_ms: number };
  effective_delay: { primary_ms: number; secondary_ms: number };
  delay_components: {
    measured_hardware_latency_ms: { primary: number; secondary: number };
    automatic_compensation_ms: { primary: number; secondary: number };
    manual_trim_ms: { primary: number; secondary: number };
  };
  metrics: Metrics;
  events: EventItem[];
};

type EventItem = { id: number; category: string; message: string; created_at: string };
type Profile = { id: number; name: string; updated_at?: string };
type Settings = { automatic_reconnect: boolean; developer_mode: boolean };
type QualityMode = "cinematic" | "balanced" | "performance" | "reduced";
type DelayKey = "primary_manual_ms" | "secondary_manual_ms";
type VolumeKey = "master" | "primary" | "secondary";

let backendQueue: Promise<unknown> = Promise.resolve();

function backendRequest<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const request = backendQueue.catch(() => undefined).then(() => invoke<T>("backend_request", { method, params }));
  backendQueue = request.catch(() => undefined);
  return request;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const blankMetrics: Metrics = {
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
  last_error: null,
  selected_output_count: 0,
  active_output_stream_count: 0,
  active_playback_worker_count: 0,
  preview_stream_count: 0,
  routing_session_count: 0,
  queue_depths: {},
  queue_latency_ms: {},
  endpoint_clock_frames: {},
  endpoint_clock_position_ms: {},
  relative_clock_error_ms: 0,
  drift_correction_ppm: {},
  capture_latency_ms: 0,
  render_latency_ms: {},
  automatic_compensation_primary_ms: 0,
  automatic_compensation_secondary_ms: 0,
  acoustic_offset_ms: null,
  calibration_confidence: null,
  buffer_underruns: 0,
  buffer_overruns: 0,
  reconnect_attempts: 0,
  reconnect_state: "idle",
  routing_mode: "idle",
  uncontrolled_output_name: null,
  routing_warning: null
};

const blankStatus: Status = {
  selection: { primary_id: null, secondary_id: null },
  source_id: null,
  delay: { primary_manual_ms: 0, secondary_manual_ms: 0, primary_estimated_ms: 0, secondary_estimated_ms: 0 },
  volume: { master: 1, primary: 1, secondary: 1, muted: false, balance: 0 },
  audio_mode: { name: "Balanced", sample_rate: 48000, bit_depth: 24, channels: 2, buffer_ms: 60 },
  effective_delay: { primary_ms: 0, secondary_ms: 0 },
  delay_components: {
    measured_hardware_latency_ms: { primary: 0, secondary: 0 },
    automatic_compensation_ms: { primary: 0, secondary: 0 },
    manual_trim_ms: { primary: 0, secondary: 0 }
  },
  metrics: blankMetrics,
  events: []
};

const APP_VERSION = "0.2.0";
const TRUSTED_LINKS = new Set([
  "https://github.com/1SAMAY",
  "https://github.com/1SAMAY/TwinSync-Audio",
  "https://samay-dev-portfolio.vercel.app/",
  "https://www.linkedin.com/in/samay-dudhrejiya",
  "mailto:samay4932@gmail.com"
]);

function openTrustedLink(url: string) {
  if (TRUSTED_LINKS.has(url)) void invoke("open_external", { url });
}

function initialQuality(): QualityMode {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return "reduced";
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8;
  return navigator.hardwareConcurrency <= 4 || memory <= 4 ? "performance" : "balanced";
}

export default function App() {
  useDisplayPerformance();
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [status, setStatus] = useState<Status>(blankStatus);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [settings, setSettings] = useState<Settings>({ automatic_reconnect: true, developer_mode: false });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [profileName, setProfileName] = useState("Default Pair");
  const [measurementInputId, setMeasurementInputId] = useState("");
  const [quality, setQuality] = useState<QualityMode>(initialQuality);
  const lastDevicesJson = useRef("");
  const lastStatusJson = useRef("");
  const lastProfilesJson = useRef("");
  const lastSettingsJson = useRef("");
  const refreshInFlight = useRef<Promise<void> | null>(null);
  const delayTimers = useRef<Partial<Record<DelayKey, number>>>({});
  const volumeTimers = useRef<Partial<Record<VolumeKey, number>>>({});

  const outputDevices = useMemo(() => devices.filter((device) => device.is_output), [devices]);
  const inputDevices = useMemo(() => devices.filter((device) => device.is_input), [devices]);
  const primaryName = outputDevices.find((device) => device.id === status.selection.primary_id)?.name ?? "Select primary";
  const secondaryName = outputDevices.find((device) => device.id === status.selection.secondary_id)?.name ?? "Select secondary";
  const isPlaying = ["playing", "starting", "reconnecting"].includes(status.metrics.playback_state);
  const syncHealth = Math.abs(status.metrics.relative_clock_error_ms) < 4 ? "Locked" : "Correcting";

  const setIfChanged = useCallback(<T,>(
    value: T,
    previousJson: React.MutableRefObject<string>,
    setter: React.Dispatch<React.SetStateAction<T>>
  ) => {
    const json = JSON.stringify(value);
    if (json !== previousJson.current) {
      previousJson.current = json;
      setter(value);
    }
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const task = (async () => {
      const errors: string[] = [];
      try {
        setIfChanged(await backendRequest<AudioDevice[]>("devices"), lastDevicesJson, setDevices);
      } catch (requestError) {
        errors.push(errorMessage(requestError));
      }
      try {
        setIfChanged(await backendRequest<Status>("status"), lastStatusJson, setStatus);
      } catch (requestError) {
        errors.push(errorMessage(requestError));
      }
      try {
        setIfChanged(await backendRequest<Profile[]>("profiles"), lastProfilesJson, setProfiles);
      } catch (requestError) {
        errors.push(errorMessage(requestError));
      }
      try {
        setIfChanged(await backendRequest<Settings>("settings"), lastSettingsJson, setSettings);
      } catch (requestError) {
        errors.push(errorMessage(requestError));
      }
      setError(errors.join(" "));
    })();
    refreshInFlight.current = task;
    void task.finally(() => {
      if (refreshInFlight.current === task) refreshInFlight.current = null;
    });
    return task;
  }, [setIfChanged]);

  useEffect(() => {
    document.documentElement.dataset.quality = quality;
    localStorage.setItem("twinsync-quality", quality);
  }, [quality]);

  useEffect(() => {
    const saved = localStorage.getItem("twinsync-quality") as QualityMode | null;
    if (saved && ["cinematic", "balanced", "performance", "reduced"].includes(saved)) setQuality(saved);
  }, []);

  useEffect(() => {
    let timer = 0;
    const startPolling = () => {
      window.clearInterval(timer);
      if (document.visibilityState !== "hidden") timer = window.setInterval(refresh, 2500);
    };
    const visibility = () => {
      document.documentElement.dataset.hidden = String(document.visibilityState === "hidden");
      if (document.visibilityState === "hidden") window.clearInterval(timer);
      else {
        void refresh();
        startPolling();
      }
    };
    void refresh();
    startPolling();
    document.addEventListener("visibilitychange", visibility, { passive: true });
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [refresh]);

  useEffect(() => () => {
    Object.values(delayTimers.current).forEach((timer) => window.clearTimeout(timer));
    Object.values(volumeTimers.current).forEach((timer) => window.clearTimeout(timer));
  }, []);

  const selectSpeakers = useCallback(async (primaryId: string | null, secondaryId: string | null) => {
    const primary_id = primaryId || null;
    const secondary_id = secondaryId || null;
    if (primary_id && secondary_id && primary_id === secondary_id) {
      setError("Primary and secondary speakers must be different devices.");
      return;
    }
    try {
      setStatus(await backendRequest<Status>("select_speakers", { primary_id, secondary_id }));
      setError("");
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const selectSource = useCallback(async (source_id: string | null) => {
    try {
      setStatus(await backendRequest<Status>("select_source", { source_id }));
      setError("");
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const setDelay = useCallback((which: DelayKey, rawValue: number) => {
    const value = Math.max(0, Math.min(500, rawValue || 0));
    setStatus((current) => ({ ...current, delay: { ...current.delay, [which]: value } }));
    window.clearTimeout(delayTimers.current[which]);
    delayTimers.current[which] = window.setTimeout(async () => {
      delete delayTimers.current[which];
      try {
        setStatus(await backendRequest<Status>("set_delay", { [which]: value }));
      } catch (requestError) {
        setError(errorMessage(requestError));
      }
    }, 120);
  }, []);

  const setVolume = useCallback((which: VolumeKey, rawValue: number) => {
    const value = Math.max(0, Math.min(100, rawValue || 0));
    setStatus((current) => ({
      ...current,
      volume: { ...current.volume, [which]: value / 100 }
    }));
    window.clearTimeout(volumeTimers.current[which]);
    volumeTimers.current[which] = window.setTimeout(async () => {
      delete volumeTimers.current[which];
      try {
        setStatus(await backendRequest<Status>("set_volume", { [which]: value / 100 }));
      } catch (requestError) {
        setError(errorMessage(requestError));
      }
    }, 120);
  }, []);

  const start = useCallback(async () => {
    try {
      setStatus(await backendRequest<Status>("start"));
      setError("");
    } catch (requestError) {
      setError(errorMessage(requestError));
      await refresh();
    }
  }, [refresh]);

  const stop = useCallback(async () => {
    try {
      setStatus(await backendRequest<Status>("stop"));
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const testSound = useCallback(async (device_id: string | null) => {
    if (!device_id) return;
    try {
      setStatus(await backendRequest<Status>("test_sound", { device_id }));
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const calibrate = useCallback(async () => {
    try {
      const result = await backendRequest<{ message: string; confidence?: number }>("calibrate", {
        measurement_input_id: measurementInputId || null
      });
      setMessage(result.message);
      setError("");
      await refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, [measurementInputId, refresh]);

  const saveProfile = useCallback(async () => {
    try {
      await backendRequest("save_profile", { name: profileName });
      await refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, [profileName, refresh]);

  const loadProfile = useCallback(async (profile_id: number) => {
    try {
      setStatus(await backendRequest<Status>("load_profile", { profile_id }));
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const updateSettings = useCallback(async (next: Partial<Settings>) => {
    try {
      setSettings(await backendRequest<Settings>("set_settings", next));
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const exportDiagnostics = useCallback(async () => {
    try {
      const result = await backendRequest<{ path: string }>("export_diagnostics");
      setMessage(`Diagnostics exported to ${result.path}`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#overview" aria-label="TwinSync Audio home">
          <span className="brand-mark">TS</span>
          <span><strong>TwinSync</strong><small>Audio v{APP_VERSION}</small></span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#routing">Routing</a>
          <a href="#sync">Sync</a>
          <a href="#diagnostics">Diagnostics</a>
          <a href="#settings">Settings</a>
        </nav>
        <div className={`state-pill ${status.metrics.playback_state}`}><span />{status.metrics.playback_state}</div>
      </header>

      {(error || message) && (
        <div className={`notice ${error ? "error" : "success"}`} role="status">
          <span>{error || message}</span>
          <button aria-label="Dismiss message" onClick={() => { setError(""); setMessage(""); }}>×</button>
        </div>
      )}

      <section className="cinematic-stage" id="overview" aria-labelledby="hero-title">
        <div className="aurora" aria-hidden="true" />
        <div className="scene" aria-hidden="true">
          <SpeakerVisual side="primary" name={primaryName} delay={status.effective_delay.primary_ms} active={isPlaying} />
          <div className="audio-source">
            <div className="source-core"><span>LIVE</span></div>
            <div className="wave-path left"><i /><i /><i /><i /></div>
            <div className="wave-path right"><i /><i /><i /><i /></div>
          </div>
          <SpeakerVisual side="secondary" name={secondaryName} delay={status.effective_delay.secondary_ms} active={isPlaying} />
        </div>
        <div className="hero-copy">
          <p className="eyebrow">Precision dual-output routing</p>
          <h1 id="hero-title">One source.<br /><em>Two clocks.</em></h1>
          <p>Independent delay, acoustic calibration, endpoint monitoring, and adaptive drift control for Windows audio.</p>
          <div className="hero-actions">
            <button className="primary-action" onClick={start} disabled={isPlaying}>Start session</button>
            <a href="#routing">Configure outputs <span>↓</span></a>
          </div>
        </div>
        <div className="stage-readout">
          <Metric label="Clock delta" value={`${status.metrics.relative_clock_error_ms.toFixed(2)} ms`} />
          <Metric label="Sync state" value={syncHealth} />
          <Metric label="Route" value={status.metrics.routing_mode} />
        </div>
      </section>

      {status.metrics.routing_warning && <div className="routing-warning">{status.metrics.routing_warning}</div>}

      <section className="section-grid" id="routing">
        <div className="section-heading">
          <p className="eyebrow">01 / Routing</p>
          <h2>Choose the physical endpoints.</h2>
          <p>TwinSync only opens the selected pair. Windows-default playback is identified whenever Windows retains control of that endpoint.</p>
        </div>
        <div className="glass-panel route-panel">
          <DeviceSelector label="Primary output" value={status.selection.primary_id} devices={outputDevices}
            onChange={(value) => selectSpeakers(value, status.selection.secondary_id)} />
          <DeviceSelector label="Secondary output" value={status.selection.secondary_id} devices={outputDevices}
            onChange={(value) => selectSpeakers(status.selection.primary_id, value)} />
          <label className="device-selector"><span>Routing source</span><select value={status.source_id ?? ""}
            onChange={(event) => void selectSource(event.target.value || null)}>
            <option value="">Windows default loopback — one endpoint remains under Windows control</option>
            {inputDevices.map((device) => <option key={device.id} value={device.id}>{device.name} — control both outputs</option>)}
          </select></label>
          <div className="button-row">
            <button onClick={() => testSound(status.selection.primary_id)}>Test primary</button>
            <button onClick={() => testSound(status.selection.secondary_id)}>Test secondary</button>
            <button onClick={() => selectSpeakers(status.selection.secondary_id, status.selection.primary_id)}>Swap</button>
          </div>
          <div className="device-list">
            {outputDevices.length ? outputDevices.map((device) => <DeviceRow key={device.id} device={device} />) : (
              <article className="empty-row"><strong>No playback endpoints</strong><span>Connect speakers in Windows Sound, then refresh.</span></article>
            )}
          </div>
        </div>
      </section>

      <section className="section-grid reverse" id="sync">
        <div className="section-heading">
          <p className="eyebrow">02 / Synchronization</p>
          <h2>Trim each speaker. Never both by accident.</h2>
          <p>Hardware latency feeds automatic compensation. Manual trim is then added only to the speaker you change.</p>
          <div className="component-ledger">
            <LedgerRow label="Measured hardware" primary={status.delay.primary_estimated_ms} secondary={status.delay.secondary_estimated_ms} />
            <LedgerRow label="Automatic compensation" primary={status.metrics.automatic_compensation_primary_ms} secondary={status.metrics.automatic_compensation_secondary_ms} />
            <LedgerRow label="Manual trim" primary={status.delay.primary_manual_ms} secondary={status.delay.secondary_manual_ms} />
            <LedgerRow label="Queue latency" primary={status.metrics.queue_latency_ms.primary ?? 0} secondary={status.metrics.queue_latency_ms.secondary ?? 0} />
          </div>
        </div>
        <div className="glass-panel sync-panel">
          <DelayControl label="Primary manual trim" value={status.delay.primary_manual_ms}
            onChange={(value) => setDelay("primary_manual_ms", value)} />
          <DelayControl label="Secondary manual trim" value={status.delay.secondary_manual_ms}
            onChange={(value) => setDelay("secondary_manual_ms", value)} />
          <VolumeControl label="Primary volume" value={status.volume.primary * 100}
            onChange={(value) => setVolume("primary", value)} />
          <VolumeControl label="Secondary volume" value={status.volume.secondary * 100}
            onChange={(value) => setVolume("secondary", value)} />
          <div className="calibration-box">
            <div><strong>Acoustic calibration</strong><span>Choose a microphone for repeated chirp measurement, or leave blank for guided listening.</span></div>
            <select aria-label="Measurement microphone" value={measurementInputId} onChange={(event) => setMeasurementInputId(event.target.value)}>
              <option value="">Guided — no microphone</option>
              {inputDevices.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}
            </select>
            <button className="primary-action" onClick={calibrate}>Run calibration</button>
          </div>
        </div>
      </section>

      <section className="diagnostics-section" id="diagnostics">
        <div className="section-heading wide">
          <p className="eyebrow">03 / Diagnostics</p>
          <h2>See the routing session, not a guess.</h2>
        </div>
        <div className="diagnostic-grid">
          <Metric label="Sync status" value={syncHealth} />
          <Metric label="Relative delay" value={`${status.metrics.relative_clock_error_ms.toFixed(2)} ms`} />
          <Metric label="Device health" value={status.metrics.connection_health} />
          <Metric label="Calibration confidence" value={status.metrics.calibration_confidence === null ? "Not measured" : `${Math.round(status.metrics.calibration_confidence * 100)}%`} />
          <Metric label="Reconnect state" value={status.metrics.reconnect_state} />
          <Metric label="Underruns" value={String(status.metrics.buffer_underruns)} />
        </div>
        {settings.developer_mode && <DeveloperDiagnostics metrics={status.metrics} />}
        <div className="diagnostic-actions">
          <label className="toggle"><input type="checkbox" checked={settings.developer_mode}
            onChange={(event) => void updateSettings({ developer_mode: event.target.checked })} /><span />Developer mode</label>
          <button onClick={exportDiagnostics}>Export private-safe diagnostics</button>
        </div>
      </section>

      <section className="lower-grid">
        <div className="glass-panel">
          <p className="eyebrow">Profiles</p>
          <h2>Recall a known room.</h2>
          <div className="profile-save">
            <input aria-label="Profile name" value={profileName} onChange={(event) => setProfileName(event.target.value)} />
            <button onClick={saveProfile}>Save profile</button>
          </div>
          <div className="profile-list">{profiles.map((profile) => <ProfileButton key={profile.id} profile={profile} onLoad={loadProfile} />)}</div>
        </div>

        <div className="glass-panel" id="settings">
          <p className="eyebrow">Settings</p>
          <h2>Render only what this machine needs.</h2>
          <div className="quality-grid">
            {(["cinematic", "balanced", "performance", "reduced"] as QualityMode[]).map((mode) => (
              <button key={mode} className={quality === mode ? "selected" : ""} onClick={() => setQuality(mode)}>{mode}</button>
            ))}
          </div>
          <label className="toggle"><input type="checkbox" checked={settings.automatic_reconnect}
            onChange={(event) => void updateSettings({ automatic_reconnect: event.target.checked })} /><span />Automatic reconnect</label>
          <p className="setting-note">Animations pause while hidden. Reduced Motion also follows the Windows accessibility preference.</p>
        </div>

        <div className="glass-panel event-panel">
          <p className="eyebrow">Session log</p>
          <h2>Recent local events.</h2>
          <div className="event-list">{status.events.map((event) => <EventRow key={event.id} event={event} />)}</div>
        </div>

        <div className="glass-panel about-panel">
          <p className="eyebrow">TwinSync Audio v{APP_VERSION}</p>
          <h2>Local by design.</h2>
          <p>No account, telemetry, cloud audio, ads, or silent dependency downloads.</p>
          <div className="link-grid">
            <button onClick={() => openTrustedLink("https://github.com/1SAMAY/TwinSync-Audio")}><strong>Repository</strong><small>1SAMAY/TwinSync-Audio</small></button>
            <button onClick={() => openTrustedLink("https://github.com/1SAMAY")}><strong>Developer</strong><small>SAMAY DUDHREJIYA</small></button>
            <button onClick={() => openTrustedLink("mailto:samay4932@gmail.com")}><strong>Contact</strong><small>samay4932@gmail.com</small></button>
          </div>
        </div>
      </section>

      <footer>Copyright © 2026 SAMAY DUDHREJIYA · Windows x86_64</footer>

      <aside className="playback-hud" aria-label="Persistent playback controls">
        <div className="hud-state"><span className={status.metrics.playback_state} /><div><small>Session</small><strong>{status.metrics.playback_state}</strong></div></div>
        <div className="hud-device"><small>Primary</small><strong>{primaryName}</strong></div>
        <div className="hud-device"><small>Secondary</small><strong>{secondaryName}</strong></div>
        <div className="hud-health"><small>Sync</small><strong>{syncHealth} · {status.metrics.connection_health}</strong></div>
        <label className="hud-volume"><span>Master</span><input aria-label="Master volume" type="range" min={0} max={100}
          value={status.volume.master * 100} onChange={(event) => setVolume("master", Number(event.target.value))} /></label>
        <div className="hud-buttons">
          <button onClick={start} disabled={isPlaying}>Start</button>
          <button onClick={stop} disabled={!isPlaying}>Stop</button>
          <button className="emergency" onClick={stop}>Emergency stop</button>
          <button aria-label="Open settings" onClick={() => document.getElementById("settings")?.scrollIntoView()}>⚙</button>
        </div>
      </aside>
    </main>
  );
}

const SpeakerVisual = memo(function SpeakerVisual({ side, name, delay, active }: { side: string; name: string; delay: number; active: boolean }) {
  return (
    <div className={`speaker-rig ${side} ${active ? "active" : ""}`}>
      <div className="clock-ring"><span>{delay.toFixed(0)}<small>ms</small></span></div>
      <div className="speaker-object"><i className="driver high" /><i className="driver low" /><b /></div>
      <strong>{name}</strong>
    </div>
  );
});

const Metric = memo(function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
});

const DeviceSelector = memo(function DeviceSelector({ label, value, devices, onChange }: {
  label: string; value: string | null; devices: AudioDevice[]; onChange: (value: string | null) => void;
}) {
  return (
    <label className="device-selector"><span>{label}</span><select value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}>
      <option value="">Select an output</option>
      {devices.map((device) => <option key={device.id} value={device.id}>{device.name}{device.is_default ? " — Windows default" : ""}</option>)}
    </select></label>
  );
});

const DelayControl = memo(function DelayControl({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="range-control"><span>{label}</span><input min={0} max={500} step={1} type="range" value={value}
    onChange={(event) => onChange(Number(event.target.value))} /><output>{Math.round(value)} ms</output></label>;
});

const VolumeControl = memo(function VolumeControl({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="range-control"><span>{label}</span><input min={0} max={100} step={1} type="range" value={value}
    onChange={(event) => onChange(Number(event.target.value))} /><output>{Math.round(value)}%</output></label>;
});

const LedgerRow = memo(function LedgerRow({ label, primary, secondary }: { label: string; primary: number; secondary: number }) {
  return <div><span>{label}</span><strong>A {primary.toFixed(1)} ms</strong><strong>B {secondary.toFixed(1)} ms</strong></div>;
});

const DeviceRow = memo(function DeviceRow({ device }: { device: AudioDevice }) {
  return <article className="device-row"><span className="device-dot" /><div><strong>{device.name}</strong><span>{device.connection_type}{device.is_default ? " · Windows default" : ""}</span></div><small>{device.status}</small></article>;
});

const ProfileButton = memo(function ProfileButton({ profile, onLoad }: { profile: Profile; onLoad: (profileId: number) => void }) {
  return <button onClick={() => onLoad(profile.id)}><span>{profile.name}</span><small>Load →</small></button>;
});

const EventRow = memo(function EventRow({ event }: { event: EventItem }) {
  return <article><span>{event.category}</span><strong>{event.message}</strong><small>{event.created_at}</small></article>;
});

const DeveloperDiagnostics = memo(function DeveloperDiagnostics({ metrics }: { metrics: Metrics }) {
  const rows = [
    ["Endpoint clock A", `${(metrics.endpoint_clock_position_ms.primary ?? 0).toFixed(2)} ms`],
    ["Endpoint clock B", `${(metrics.endpoint_clock_position_ms.secondary ?? 0).toFixed(2)} ms`],
    ["Relative clock error", `${metrics.relative_clock_error_ms.toFixed(3)} ms`],
    ["Queue depth", JSON.stringify(metrics.queue_depths)],
    ["Drift correction", JSON.stringify(metrics.drift_correction_ppm) + " ppm"],
    ["Capture latency", `${metrics.capture_latency_ms.toFixed(2)} ms`],
    ["Render latency", JSON.stringify(metrics.render_latency_ms) + " ms"],
    ["Acoustic offset", metrics.acoustic_offset_ms === null ? "Not measured" : `${metrics.acoustic_offset_ms.toFixed(2)} ms`],
    ["Underruns / overruns", `${metrics.buffer_underruns} / ${metrics.buffer_overruns}`],
    ["Workers / streams", `${metrics.active_playback_worker_count} / ${metrics.active_output_stream_count}`],
    ["Reconnect attempts", String(metrics.reconnect_attempts)],
    ["Last audio error", metrics.last_error ?? "None"]
  ];
  return <div className="developer-grid">{rows.map(([label, value]) => <div key={label}><span>{label}</span><code>{value}</code></div>)}</div>;
});
