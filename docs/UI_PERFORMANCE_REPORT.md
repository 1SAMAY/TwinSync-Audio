# UI Performance Report — v0.2.0

The v0.2.0 interface uses CSS transforms, opacity, gradients, and native form controls; it adds no WebGL or animation dependency. React state is never updated per animation frame.

- One serialized frontend IPC queue prevents overlapping backend commands.
- One guarded refresh promise prevents concurrent status refreshes.
- Delay and volume changes are optimistic and debounced by 120 ms.
- Polling and CSS animation work pause while the document is hidden.
- Unchanged devices, status, profiles, and settings do not trigger React state writes.
- Repeated rows and controls are memoized.
- Cinematic, Balanced, Performance, and Reduced Motion modes use one DOM structure.
- Low-core/low-memory systems default to Performance.
- Windows `prefers-reduced-motion` disables animation and smooth scrolling.
- CSS vector geometry and responsive breakpoints support DPI scaling without bitmap enlargement.

Physical 100/125/150/200% DPI, mixed-monitor DPI, GPU/driver, and audio-under-visual-load results remain part of `HARDWARE_TEST_CHECKLIST.md`.
