// Field inventory and defaults mirror templates/setup.html exactly - see
// .superpowers/sdd/2026-08-30-ui-overhaul-4-cutover/task-3-report.md for the
// field-by-field extraction this was ported against.

export interface SetupData {
  LITE_MODE: boolean;
  TORBOX_API_KEY: string;
  JELLYFIN_URL: string;
  JELLYFIN_API_KEY: string;
  SEERR_URL: string;
  SEERR_API_KEY: string;
  TMDB_API_KEY: string;
  QUALITY_PREFERENCE: string;
  AUDIO_LANGUAGE_PREFERENCE: string;
  PREFER_HEVC: boolean;
  ALLOW_4K: boolean;
  CATBOX_MODE: boolean;
  CATBOX_HOST: string;
  DISCORD_WEBHOOK_URL: string;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  TRAKT_CLIENT_ID: string;
  TRAKT_CLIENT_SECRET: string;
  OPENSUBTITLES_API_KEY: string;
  OPENSUBTITLES_LANGUAGES: string;
  ZILEAN_MODE: 'external' | 'native';
  ZILEAN_URL: string;
  ZILEAN_ENABLED: boolean;
  RADARR_URL: string;
  RADARR_API_KEY: string;
  SONARR_URL: string;
  SONARR_API_KEY: string;
}

// Mirrors the literal defaults baked into templates/setup.html's inputs
// (value="..." / checked attributes), not placeholders.
export const DEFAULT_SETUP_DATA: SetupData = {
  LITE_MODE: false,
  TORBOX_API_KEY: '',
  JELLYFIN_URL: '',
  JELLYFIN_API_KEY: '',
  SEERR_URL: '',
  SEERR_API_KEY: '',
  TMDB_API_KEY: '',
  QUALITY_PREFERENCE: '1080p,2160p,720p',
  AUDIO_LANGUAGE_PREFERENCE: '',
  PREFER_HEVC: true,
  ALLOW_4K: true,
  CATBOX_MODE: false,
  CATBOX_HOST: '',
  DISCORD_WEBHOOK_URL: '',
  TELEGRAM_BOT_TOKEN: '',
  TELEGRAM_CHAT_ID: '',
  TRAKT_CLIENT_ID: '',
  TRAKT_CLIENT_SECRET: '',
  OPENSUBTITLES_API_KEY: '',
  OPENSUBTITLES_LANGUAGES: '',
  ZILEAN_MODE: 'external',
  ZILEAN_URL: '',
  ZILEAN_ENABLED: false,
  RADARR_URL: '',
  RADARR_API_KEY: '',
  SONARR_URL: '',
  SONARR_API_KEY: '',
};

export type SetField = <K extends keyof SetupData>(key: K, value: SetupData[K]) => void;

/** Mirrors setup.html's collect(): every field, booleans coerced to the
 * "true"/"false" strings FormData.append() would produce, strings trimmed.
 * Both the Test buttons and the final save post this same full snapshot,
 * not just the fields relevant to one kind - see the report for why. */
export function buildFormData(data: SetupData): FormData {
  const fd = new FormData();
  (Object.keys(data) as (keyof SetupData)[]).forEach((key) => {
    const value = data[key];
    fd.append(key, typeof value === 'boolean' ? (value ? 'true' : 'false') : String(value).trim());
  });
  return fd;
}
