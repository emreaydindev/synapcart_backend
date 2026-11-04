/** ISO-8601 UTC timestamp, the format every timestamp column uses. */
export const nowIso = (d: Date = new Date()): string => d.toISOString();

export const addMs = (ms: number, from: Date = new Date()): string => new Date(from.getTime() + ms).toISOString();

export const HOUR = 3_600_000;
export const MINUTE = 60_000;

/** Quotas reset at 00:00 UTC. */
export const todayUtc = (d: Date = new Date()): string => d.toISOString().slice(0, 10);

export const isPast = (iso: string | null | undefined, now: Date = new Date()): boolean =>
  !!iso && new Date(iso).getTime() <= now.getTime();
