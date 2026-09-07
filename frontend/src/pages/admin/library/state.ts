export const VIEWS = ['all', 'attention', 'wanted', 'queue', 'incomplete', 'unmirrored'] as const;
export const STATUSES = ['success', 'wanted', 'upcoming', 'failed', 'pending'] as const;
export const PROBLEMS = ['failed', 'wanted', 'unplayable', 'missing_episodes', 'in_retry_queue', 'no_requester', 'not_mirrored'] as const;
export const SORTS = ['title', 'status', 'requester', 'updated', 'created'] as const;

export type LibraryState = {
  view: string; q: string; status: string[]; type: string; problem: string; requester: string; added: string;
  sort: string; order: 'asc' | 'desc'; page: number; perPage: number; open: string | null;
};

export const DEFAULT_STATE: LibraryState = {
  view: 'all', q: '', status: [], type: '', problem: '', requester: '', added: '',
  sort: '', order: 'desc', page: 1, perPage: 50, open: null,
};

export function parseHash(hash: string): LibraryState {
  const [tab, query = ''] = hash.replace(/^#/, '').split('?');
  if (tab !== 'library') return { ...DEFAULT_STATE };
  const p = new URLSearchParams(query);
  const pick = (k: string, allowed: readonly string[]) => (allowed.includes(p.get(k) || '') ? (p.get(k) as string) : '');
  const page = parseInt(p.get('page') || '1', 10);
  const perPage = parseInt(p.get('per_page') || '50', 10);
  return {
    view: pick('view', VIEWS) || 'all',
    q: p.get('q') || '',
    status: (p.get('status') || '').split(',').filter((s) => (STATUSES as readonly string[]).includes(s)),
    type: pick('type', ['movie', 'series']),
    problem: pick('problem', PROBLEMS),
    requester: p.get('requester') || '',
    added: pick('added', ['24h', '7d', '30d']),
    sort: pick('sort', SORTS),
    order: p.get('order') === 'asc' ? 'asc' : 'desc',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    perPage: [25, 50, 100, 200].includes(perPage) ? perPage : 50,
    open: p.get('open') || null,
  };
}

export function toHash(s: LibraryState): string {
  const p = new URLSearchParams();
  if (s.view !== 'all') p.set('view', s.view);
  if (s.q) p.set('q', s.q);
  if (s.status.length) p.set('status', s.status.join(','));
  if (s.type) p.set('type', s.type);
  if (s.problem) p.set('problem', s.problem);
  if (s.requester) p.set('requester', s.requester);
  if (s.added) p.set('added', s.added);
  if (s.sort) { p.set('sort', s.sort); if (s.order !== 'desc') p.set('order', s.order); }
  if (s.page !== 1) p.set('page', String(s.page));
  if (s.perPage !== 50) p.set('per_page', String(s.perPage));
  if (s.open) p.set('open', s.open);
  const q = p.toString();
  return q ? `#library?${q}` : '#library';
}

export function toQuery(s: LibraryState): Record<string, string | string[]> {
  return {
    view: s.view, q: s.q, status: s.status, type: s.type, problem: s.problem, requester: s.requester,
    added: s.added, sort: s.sort, order: s.order, page: String(s.page), per_page: String(s.perPage),
  };
}
