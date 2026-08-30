export const ICON_NAMES = [
  'discover', 'library', 'watchlist', 'search', 'requests',
  'wanted', 'settings', 'admin', 'manual', 'setup', 'login',
] as const;

export type IconName = (typeof ICON_NAMES)[number];

const PATHS: Record<IconName, string> = {
  discover: 'M12 3a9 9 0 100 18 9 9 0 000-18zM15.5 8.5l-2.2 4.8-4.8 2.2 2.2-4.8 4.8-2.2z',
  library: 'M4 4h7v16H6a2 2 0 01-2-2V4zm9 0h7v14a2 2 0 01-2 2h-5V4z',
  watchlist: 'M12 4l2.5 5.2 5.5.8-4 3.9.9 5.6-4.9-2.7-4.9 2.7.9-5.6-4-3.9 5.5-.8z',
  search: 'M16.5 16.5L21 21M17 11a6 6 0 11-12 0 6 6 0 0112 0z',
  requests: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  wanted: 'M12 7v5l4 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  settings: 'M4 8h9M17 8h3M4 16h4M12 16h8M14 5v6M9 13v6',
  admin: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.6 14.6a1.7 1.7 0 00.3 1.9 2 2 0 11-2.8 2.8 1.7 1.7 0 00-2.9 1.2 2 2 0 11-4 0 1.7 1.7 0 00-2.9-1.2 2 2 0 11-2.8-2.8 1.7 1.7 0 00-1.2-2.9 2 2 0 110-4 1.7 1.7 0 001.2-2.9 2 2 0 112.8-2.8A1.7 1.7 0 0010.2 3a2 2 0 114 0 1.7 1.7 0 002.9 1.2 2 2 0 112.8 2.8 1.7 1.7 0 001.2 2.9 2 2 0 110 4 1.7 1.7 0 00-1.5 1.7z',
  manual: 'M4 4h7v16H6a2 2 0 01-2-2V4zm9 0h7v14a2 2 0 01-2 2h-5V4zM8 8h3M8 12h3',
  setup: 'M5 7h14M5 12h9M5 17h6M17 15l2 2 3-4',
  login: 'M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l-5-5 5-5M5 12h9',
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
