import type {
  TmdbItem,
  TmdbDetail,
  Provider,
  WatchlistItem,
  UserRecord,
  UserRequest,
  SessionInfo,
  MediaType,
  WantedMovie,
  WantedEpisode,
  PersonDetail,
} from './types';

export const csrfToken = (): string => {
  return document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content || '';
};

async function http<T>(url: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || 'GET').toUpperCase();
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRFToken'] = csrfToken();
    if (init.body && !(init.body instanceof FormData)) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }
  }
  const resp = await fetch(url, { ...init, headers, credentials: 'same-origin' });
  if (resp.status === 401) {
    if (typeof window !== 'undefined' && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/login';
    }
    throw new Error('unauthorized');
  }
  if (!resp.ok) {
    let detail = '';
    try {
      const j = await resp.json();
      detail = j.error || j.detail || JSON.stringify(j);
    } catch {
      detail = await resp.text();
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return (await resp.json()) as T;
}

/** POST helper for the Jinja maintenance/blacklist routes that are plain form
 * posts today: the Flask handler flashes a message and responds with a
 * redirect to the dashboard, not JSON. fetch() follows that redirect on its
 * own, so success is just response.ok after the follow - there is no JSON
 * body to parse. */
async function formPost(url: string, body?: Record<string, string>): Promise<void> {
  const headers: Record<string, string> = { 'X-CSRFToken': csrfToken() };
  let payload: string | undefined;
  if (body) {
    payload = new URLSearchParams(body).toString();
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
  }
  const resp = await fetch(url, { method: 'POST', headers, body: payload, credentials: 'same-origin' });
  if (resp.status === 401) {
    if (typeof window !== 'undefined' && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/login';
    }
    throw new Error('unauthorized');
  }
  if (!resp.ok) throw new Error(`${resp.status}`);
}

export const api = {
  // Discovery
  search: (q: string) =>
    http<{ results: TmdbItem[] }>(`/ui/api/discover/search?q=${encodeURIComponent(q)}`),
  trending: (type: 'all' | 'movie' | 'tv' = 'all', window: 'day' | 'week' = 'week') =>
    http<{ results: TmdbItem[] }>(`/ui/api/discover/trending?type=${type}&window=${window}`),
  popular: (type: MediaType = 'movie') =>
    http<{ results: TmdbItem[] }>(`/ui/api/discover/popular?type=${type}`),
  topRated: (type: MediaType = 'movie') =>
    http<{ results: TmdbItem[] }>(`/ui/api/discover/top-rated?type=${type}`),
  nowPlaying: () => http<{ results: TmdbItem[] }>('/ui/api/discover/now-playing'),
  upcoming: () => http<{ results: TmdbItem[] }>('/ui/api/discover/upcoming'),
  onTheAir: () => http<{ results: TmdbItem[] }>('/ui/api/discover/on-the-air'),
  providers: (type: MediaType = 'movie') =>
    http<{ providers: Provider[] }>(`/ui/api/discover/providers?type=${type}`),
  byProvider: (type: MediaType, providerId: number, sortBy?: string) =>
    http<{ results: TmdbItem[] }>(
      `/ui/api/discover/by-provider?type=${type}&provider_id=${providerId}${sortBy ? `&sort_by=${sortBy}` : ''}`,
    ),
  byGenre: (type: MediaType, genreId: number, yearFrom?: number | null, yearTo?: number | null) =>
    http<{ results: TmdbItem[] }>(
      `/ui/api/discover/by-genre?type=${type}&genre_id=${genreId}` +
      (yearFrom ? `&year_from=${yearFrom}` : '') + (yearTo ? `&year_to=${yearTo}` : ''),
    ),
  genreTabs: () =>
    http<{ tabs: GenreRule[] }>('/ui/api/discover/genre-tabs'),
  genreTabsConfig: () =>
    http<{ tabs: GenreRule[] }>('/ui/api/discover/genre-tabs/config'),
  setGenreTabsConfig: (tabs: GenreRule[]) =>
    http<{ ok: boolean }>('/ui/api/discover/genre-tabs/config', {
      method: 'POST',
      body: JSON.stringify({ tabs }),
    }),
  details: (type: MediaType, id: number) =>
    http<TmdbDetail>(`/ui/api/discover/details?type=${type}&id=${id}`),
  person: (id: number) =>
    http<PersonDetail>(`/ui/api/person/${id}`),
  favoriteActors: () =>
    http<{ actors: Array<{ person_id: number; name: string; profile_path: string | null }> }>(
      '/ui/api/favorite-actors',
    ),
  followActor: (personId: number, name: string, profilePath: string | null) =>
    http<{ ok: boolean }>(`/ui/api/favorite-actors/${personId}`, {
      method: 'POST',
      body: JSON.stringify({ name, profile_path: profilePath }),
    }),
  unfollowActor: (personId: number) =>
    http<{ ok: boolean }>(`/ui/api/favorite-actors/${personId}/remove`, { method: 'POST' }),
  addToLibrary: (
    tmdb_id: number,
    media_type: MediaType,
    title: string,
    opts?: { monitor_mode?: 'all' | 'future' | 'selected'; seasons?: number[] },
  ) =>
    http<{ status: string; request_id?: number; imdb_id?: string; error?: string }>(
      '/ui/api/discover/add',
      {
        method: 'POST',
        body: JSON.stringify({ tmdb_id, media_type, title, ...opts }),
      },
    ),

  // Watchlist
  watchlist: () => http<{ items: WatchlistItem[] }>('/ui/api/watchlist'),
  watchlistAdd: (params: {
    imdb_id: string;
    tmdb_id: number | null;
    media_type: MediaType;
    title: string;
    poster_path: string | null;
  }) =>
    http<{ ok: boolean }>('/ui/api/watchlist/add', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  watchlistRemove: (imdb_id: string, media_type: MediaType) =>
    http<{ ok: boolean }>('/ui/api/watchlist/remove', {
      method: 'POST',
      body: JSON.stringify({ imdb_id, media_type }),
    }),

  // User requests
  userRequests: (status?: string) =>
    http<{ items: UserRequest[] }>(
      '/ui/api/user-requests' + (status ? `?status=${status}` : ''),
    ),
  approveRequest: (id: number) =>
    http<{ ok: boolean }>(`/ui/api/user-requests/${id}/approve`, { method: 'POST' }),
  denyRequest: (id: number, note?: string) =>
    http<{ ok: boolean }>(`/ui/api/user-requests/${id}/deny`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),

  // Users (admin)
  users: () => http<{ users: UserRecord[] }>('/ui/api/users'),
  createUser: (params: {
    username: string;
    password: string;
    role?: 'user' | 'admin';
    auto_approve?: boolean;
  }) =>
    http<{ ok: boolean; user_id: number; message?: string }>('/ui/api/users/create', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  updateUser: (id: number, fields: Partial<UserRecord> & { password?: string }) =>
    http<{ ok: boolean }>(`/ui/api/users/${id}/update`, {
      method: 'POST',
      body: JSON.stringify(fields),
    }),
  deleteUser: (id: number) =>
    http<{ ok: boolean }>(`/ui/api/users/${id}/delete`, { method: 'POST' }),

  // Account
  changePassword: (current: string, password: string) =>
    http<{ ok: boolean; error?: string }>('/ui/api/me/password', {
      method: 'POST',
      body: JSON.stringify({ current, password }),
    }),

  // Plugin user fields (self-service toggle)
  setPluginFields: (fields: Record<string, boolean>) =>
    http<{ ok: boolean }>('/ui/api/me/plugin-fields', {
      method: 'POST',
      body: JSON.stringify(fields),
    }),

  // Region
  setRegion: (region: string) =>
    http<{ ok: boolean; region: string }>('/ui/api/me/region', {
      method: 'POST',
      body: JSON.stringify({ region }),
    }),

  // User preferences
  setPreferences: (prefs: Record<string, boolean | string>) =>
    http<{ ok: boolean }>('/ui/api/me/preferences', {
      method: 'POST',
      body: JSON.stringify(prefs),
    }),

  // Jellyfin item lookup (single)
  jellyfinItem: (imdb_id: string) =>
    http<{ jellyfin_id: string | null; jellyfin_url: string | null }>(`/ui/api/jellyfin/item?imdb_id=${encodeURIComponent(imdb_id)}`),

  // Jellyfin batch lookup
  jellyfinItems: (imdb_ids: string[]) =>
    http<{ jellyfin_url: string | null; items: Record<string, string | null> }>(
      `/ui/api/jellyfin/items?imdb_ids=${imdb_ids.map(encodeURIComponent).join(',')}`,
    ),

  // TMDB find by IMDB id
  tmdbFind: (imdb_id: string) =>
    http<{ tmdb_id: number | null; media_type: string | null }>(`/ui/api/tmdb/find?imdb_id=${encodeURIComponent(imdb_id)}`),

  // Library / dashboard
  session: () => http<SessionInfo>('/ui/api/session'),
  stats: () => http<any>('/ui/api/stats'),
  libraryStatusMap: () => http<Record<string, string>>('/ui/api/library/status-map'),
  libraryMovies: () => http<{ items: any[] }>('/ui/api/library/movies'),
  recent: () => http<{ items: any[] }>('/ui/api/activity'),
  myRequests: () => http<{ items: any[] }>('/ui/api/user-requests?mine=1'),
  myQuota: () => http<QuotaInfo>('/ui/api/me/quota'),
  scraperHealth: () => http<ScraperHealth>('/ui/api/scraper-health'),
  adminLogs: (limit?: number, level?: string) => {
    const params = new URLSearchParams();
    if (limit !== undefined) params.set('limit', String(limit));
    if (level) params.set('level', level);
    const qs = params.toString();
    return http<{ lines: LogLine[] }>(`/ui/api/logs${qs ? `?${qs}` : ''}`);
  },

  // Admin: Overview tab
  health: () => http<{ services: HealthService[] }>('/ui/api/health'),
  activity: () => http<{ events: ActivityEvent[] }>('/ui/api/activity'),
  webhookSecret: () => http<{ secret: string; source: string }>('/ui/api/webhook-secret'),
  torboxList: () => http<{ torrents: TorboxTorrent[] }>('/ui/api/torbox-list'),
  retryQueue: () => http<{ items: unknown[] }>('/ui/api/retry-queue'),
  releases: () => http<{ releases: Release[] }>('/ui/api/releases'),
  torboxQuota: () => http<TorboxQuota>('/ui/api/torbox-quota'),
  metricsSummary: () => http<MetricsSummary>('/ui/api/metrics-summary'),
  storage: () => http<{ folders: StorageFolder[] }>('/ui/api/storage'),
  libraryHealth: () => http<LibraryHealth>('/ui/api/orphans'),

  // Arr import
  arrTest: (kind: 'radarr' | 'sonarr') =>
    http<{ ok: boolean; error?: string }>(`/ui/api/arr-import/test-${kind}`, {
      method: 'POST',
    }),
  arrRun: (kind: 'radarr' | 'sonarr') =>
    http<{ ok: boolean }>(`/ui/api/arr-import/${kind}`, {
      method: 'POST',
      body: JSON.stringify({ only_monitored: true }),
    }),
  arrStatus: () =>
    http<{
      running: boolean;
      kind: string | null;
      total: number;
      done: number;
      added: number;
      skipped: number;
      errors: number;
      message: string;
    }>('/ui/api/arr-import/status'),

  autoAddNow: () =>
    http<{ ok: boolean; message?: string }>('/ui/api/auto-add-now', { method: 'POST' }),

  // Wanted lists
  wantedMovies: () => http<{ items: WantedMovie[] }>('/ui/api/wanted-movies'),
  wantedRecheck: () => http<{ ok: boolean; message?: string }>('/ui/api/wanted-recheck', { method: 'POST' }),
  wantedEpisodes: () => http<{ items: WantedEpisode[] }>('/ui/api/wanted-episodes'),

  // All requests (admin Requests tab)
  requestsAll: () => http<{ items: RequestRow[] }>('/ui/api/requests/all'),

  // Failed processing requests
  failedRequests: () => http<{ items: any[] }>('/ui/api/requests/failed'),
  retryRequest: (id: number) =>
    http<{ ok: boolean; title?: string }>(`/ui/api/requests/${id}/retry`, { method: 'POST' }),
  deleteRequest: (id: number) =>
    http<{ ok: boolean }>(`/ui/api/requests/${id}/delete`, { method: 'POST' }),
  // Admin only: also deletes the .strm files, so the title leaves Jellyfin/Plex.
  purgeRequest: (id: number) =>
    http<{ ok: boolean; strms: number }>(`/ui/api/requests/${id}/purge`, { method: 'POST' }),

  // Trakt
  traktStatus: () =>
    http<{ connected: boolean; username: string | null; synced_at: string | null; configured: boolean }>(
      '/ui/api/trakt/status'
    ),
  traktAuthStart: () =>
    http<{ user_code: string; verification_url: string; expires_in: number; interval: number }>(
      '/ui/api/trakt/auth/start', { method: 'POST' }
    ),
  traktAuthPoll: () =>
    http<{ status: string; username?: string; error?: string }>('/ui/api/trakt/auth/poll'),
  traktRevoke: () =>
    http<{ ok: boolean }>('/ui/api/trakt/auth/revoke', { method: 'POST' }),
  traktSync: () =>
    http<{ ok: boolean; added: number }>('/ui/api/trakt/sync', { method: 'POST' }),
  traktSyncWatched: () =>
    http<{ ok: boolean; watched: number }>('/ui/api/trakt/sync-watched', { method: 'POST' }),
  traktWatched: () =>
    http<{ imdb_ids: string[] }>('/ui/api/trakt/watched'),
  traktWatchedEpisodes: () =>
    http<{ shows: Record<string, Record<string, number[]>> }>('/ui/api/trakt/watched-episodes'),
  traktScrobble: (params: {
    action: 'start' | 'pause' | 'stop';
    media_type: string;
    imdb_id: string;
    progress: number;
    season?: number;
    episode?: number;
    title?: string;
  }) =>
    http<{ ok: boolean }>('/ui/api/trakt/scrobble', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  // Maintenance
  repairStrms: () =>
    http<{ scanned: number; ok: number; orphaned_tokens: number; relinked: number; deleted: number; skipped: number }>(
      '/ui/api/repair-strms', { method: 'POST' }
    ),
  scanTorboxLibrary: () =>
    http<{ scanned: number; imported: number; skipped: number; failed: number }>(
      '/ui/api/torbox/scan-library', { method: 'POST' }
    ),
  migrateCanonical: () =>
    http<{ scanned: number; renamed: number; merged: number; skipped: number; no_imdb: number; errors?: number }>(
      '/ui/api/migrate-canonical', { method: 'POST' }
    ),
  cleanupDuplicateStrms: () =>
    http<{ scanned: number; cleaned: number; skipped?: number }>(
      '/ui/api/cleanup-duplicate-strms', { method: 'POST' }
    ),
  seriesBackfill: () =>
    http<{ ok: boolean; started: string }>('/ui/api/series-backfill', { method: 'POST' }),

  // Maintenance tab: the 14 Jinja action forms. Each POSTs and redirects to
  // the dashboard (flash message on the reloaded page) rather than
  // returning JSON, so these go through formPost, not http().
  maintenanceRepairAll: () => formPost('/ui/repair-all'),
  maintenanceRunCleanup: () => formPost('/ui/run-cleanup'),
  maintenanceAutoUpgrade: () => formPost('/ui/auto-upgrade'),
  maintenancePackConsolidate: () => formPost('/ui/pack-consolidate'),
  maintenanceMergeSeries: () => formPost('/ui/merge-series'),
  maintenanceSyncSeerr: () => formPost('/ui/sync-movies'),
  maintenanceLibraryImport: () => formPost('/ui/library-import'),
  maintenanceFixCovers: () => formPost('/ui/refresh-images'),
  maintenanceGenerateNfos: () => formPost('/ui/generate-nfos'),
  maintenanceDbVacuum: () => formPost('/ui/db-vacuum'),
  maintenanceRecovery: () => formPost('/ui/recovery'),

  // The three JS-driven maintenance actions: these DO return JSON.
  fixImdbTitles: () =>
    http<{ fixed: Array<Record<string, unknown>>; failed: Array<Record<string, unknown>>; total: number; fixed_count: number }>(
      '/ui/api/fix-imdb-titles', { method: 'POST' }
    ),
  repairTvshowTitles: () =>
    http<{ fixed: number; skipped: number }>('/ui/api/repair-tvshow-titles', { method: 'POST' }),
  clearRetryQueue: () =>
    http<{ ok: boolean; removed: number }>('/ui/api/retry-queue/clear', { method: 'POST' }),

  // Maintenance tab: repair history feed (summary + item list).
  repairOverview: () => http<{ items: RepairItem[]; last_cleanup: RepairSummary | null }>('/ui/api/repair'),

  // Maintenance tab: small manual-input cards for actions whose live UI
  // (search candidates, TorBox list, backup list, show-override list) is
  // out of scope for this tab - each posts the same route the Jinja page's
  // per-row form used, form-encoded, plain redirect response.
  maintenanceAddMagnet: (magnet: string) => formPost('/ui/add-magnet', { magnet }),
  maintenanceTorboxDelete: (torrentId: string) => formPost('/ui/torbox-delete', { torrent_id: torrentId }),
  maintenanceBackupRestore: (name: string) => formPost('/ui/backup-restore', { name }),
  maintenanceShowOverrideDelete: (imdbId: string) =>
    formPost(`/ui/show-override-delete/${encodeURIComponent(imdbId)}`),

  // Blacklist tab
  blacklist: () => http<{ items: BlacklistItem[] }>('/ui/api/blacklist'),
  blacklistClear: (infoHash: string) => formPost(`/ui/blacklist-clear/${encodeURIComponent(infoHash)}`),

  // Auto-approve (genre rules + favorite actors)
  genres: (type: 'movie' | 'tv') =>
    http<{ genres: Array<{ id: number; name: string }> }>(`/ui/api/genres?type=${type}`),
  autoApproveGenreRules: () =>
    http<{ rules: GenreRule[] }>('/ui/api/auto-approve/genre-rules'),
  setAutoApproveGenreRules: (rules: GenreRule[]) =>
    http<{ ok: boolean }>('/ui/api/auto-approve/genre-rules', {
      method: 'POST',
      body: JSON.stringify({ rules }),
    }),
  runAutoApproveNow: () =>
    http<{ ok: boolean; started: boolean }>('/ui/api/auto-approve/run-now', { method: 'POST' }),

  // MDBList
  mdblistStatus: () =>
    http<{ connected: boolean; list_ids: string }>('/ui/api/mdblist/status'),
  mdblistConnect: (apiKey: string) =>
    http<{ ok: boolean }>('/ui/api/mdblist/connect', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    }),
  mdblistDisconnect: () =>
    http<{ ok: boolean }>('/ui/api/mdblist/disconnect', { method: 'POST' }),
  mdblistLists: () =>
    http<{ lists: Array<{ id: number; name: string }> }>('/ui/api/mdblist/lists'),
  mdblistSetLists: (listIds: (string | number)[]) =>
    http<{ ok: boolean }>('/ui/api/mdblist/lists', {
      method: 'POST',
      body: JSON.stringify({ list_ids: listIds }),
    }),
  mdblistSync: () =>
    http<{ ok: boolean; added: number }>('/ui/api/mdblist/sync', { method: 'POST' }),

  // Settings (admin)
  settings: () =>
    http<{ groups: Array<{ id: string; title: string; items: SettingItem[] }>; hot_reload: string[] }>(
      '/ui/api/settings',
    ),
  setNotificationSettings: (values: Record<string, boolean | string>) =>
    http<{ ok: boolean }>('/ui/api/settings/notifications', {
      method: 'POST',
      body: JSON.stringify(values),
    }),

  // Application shell (nav counts + TorBox pill)
  shellSummary: () => http<ShellSummary>('/ui/api/shell-summary'),
};

export type ShellSummary = {
  counts: { watchlist: number; requests: number; wanted: number };
  torbox: { state: 'ok' | 'degraded' | 'down'; label: string };
};

export type QuotaInfo = { used: number; limit: number; resets_at: string; unlimited: boolean };

export type ScraperHealth = {
  scrapers: {
    name: string;
    latency_ms: number | null;
    state: 'ok' | 'slow' | 'down' | 'unknown';
    samples: number;
  }[];
};

export type LogLine = { time: string; level: string; name: string; msg: string };

export type HealthService = { name: string; status: string };

export type ActivityEvent = {
  created_at: string;
  event: string;
  title?: string | null;
  message?: string | null;
  success?: boolean;
};

export type TorboxTorrent = {
  id: number;
  name: string;
  hash: string;
  size: number;
  download_state: string;
  download_finished: boolean;
  progress: number;
  created_at: string;
  file_count: number;
};

export type Release = { version: string; date: string; notes: string[] };

export type TorboxQuota = {
  count: number;
  limit: number;
  window_sec: number;
  by_reason: Record<string, number>;
  oldest_ts: number | null;
  resets_in_sec: number;
};

export type MetricRow = { label: string; count: number; avg_real: number | null; sum_int: number | null };

export type MetricsSummary = {
  quality: MetricRow[];
  sources: MetricRow[];
  unique_sources: MetricRow[];
  latency: MetricRow[];
  failures: MetricRow[];
};

export type StorageFolder = { path: string; count: number };

export type LibraryHealth = {
  strm_count: number;
  db_count: number;
  strm_without_db: number;
  db_without_strm: number;
};

export interface RepairItem {
  path: string;
  title: string | null;
  media_type: string | null;
  status: string;
  old_torrent_id: string | number | null;
  new_info_hash: string | null;
  reason: string | null;
  created_at: string | null;
}

export interface RepairSummary {
  scanned: number;
  repaired: number;
  deleted: number;
  unfixable: number;
  ran_at: string;
}

export interface BlacklistItem {
  info_hash: string;
  fail_count: number;
  last_error: string | null;
  last_attempt: string | null;
}

export interface SettingItem {
  key: string;
  value: any;
  kind: 'bool' | 'list' | 'int' | 'float' | 'str';
  overridden: boolean;
  hot_reload: boolean;
}

export interface RequestRow {
  id: number;
  title: string;
  imdb_id: string;
  media_type: string;
  seasons: string | null;
  status: string;
  quality: string | null;
  source: string | null;
  info_hash: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenreRule {
  media_type: 'movie' | 'tv';
  genre_id: number;
  genre_name: string;
  year_from: number | null;
  year_to: number | null;
  enabled: boolean;
}

// Image helpers  -  TMDB image CDN
export const tmdbImg = {
  poster: (p: string | null | undefined) => (p ? `https://image.tmdb.org/t/p/w342${p}` : null),
  backdrop: (p: string | null | undefined) => (p ? `https://image.tmdb.org/t/p/w1280${p}` : null),
  logo: (p: string | null | undefined) => (p ? `https://image.tmdb.org/t/p/w92${p}` : null),
  profile: (p: string | null | undefined) => (p ? `https://image.tmdb.org/t/p/w185${p}` : null),
};

// Provider IDs (NL)  -  keep in sync with backend tmdb.NL_PROVIDERS
export const NL_PROVIDER_IDS = {
  netflix: 8,
  amazon_prime: 119,
  disney_plus: 337,
  hbo_max: 1899,
  apple_tv_plus: 350,
  videoland: 563,
  npo_plus: 271,
  skyshowtime: 1773,
} as const;
