const GIB = 1024 ** 3;

export function formatGiB(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`;
}

export function formatTB(bytes: number): string {
  return `${(bytes / 1e12).toFixed(2)} TB`;
}

/** "42 min" under an hour, "1 h 05 min" above it. */
export function formatCountdown(sec: number): string {
  if (sec <= 0) return 'now';
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}

export function formatLatency(ms: number | null): string {
  if (ms == null) return '-';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

/** "3 min", "5 h", "1 d 4 h" from an age in seconds. */
export function relativeAge(sec: number): string {
  if (sec < 3600) return `${Math.max(1, Math.floor(sec / 60))} min`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h`;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  return h ? `${d} d ${h} h` : `${d} d`;
}
