export const VIEWS = ['pending', 'approved', 'denied', 'all'] as const;
export const SORTS = ['created', 'reviewed', 'user', 'title'] as const;

export type RequestsState = {
  view: string; q: string; user: string; type: string; added: string;
  sort: string; order: 'asc' | 'desc'; page: number; perPage: number; open: string | null;
};

export const DEFAULT_STATE: RequestsState = {
  view: 'pending', q: '', user: '', type: '', added: '', sort: '', order: 'desc', page: 1, perPage: 50, open: null,
};

export function parseHash(hash: string): RequestsState {
  const [tab, query = ''] = hash.replace(/^#/, '').split('?');
  if (tab !== 'requests') return { ...DEFAULT_STATE };
  const p = new URLSearchParams(query);
  const pick = (k: string, allowed: readonly string[]) => (allowed.includes(p.get(k) || '') ? (p.get(k) as string) : '');
  const page = parseInt(p.get('page') || '1', 10);
  const perPage = parseInt(p.get('per_page') || '50', 10);
  return {
    view: pick('view', VIEWS) || 'pending',
    q: p.get('q') || '',
    user: /^\d+$/.test(p.get('user') || '') ? (p.get('user') as string) : '',
    type: pick('type', ['movie', 'series']),
    added: pick('added', ['24h', '7d', '30d']),
    sort: pick('sort', SORTS),
    order: p.get('order') === 'asc' ? 'asc' : 'desc',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    perPage: [25, 50, 100, 200].includes(perPage) ? perPage : 50,
    open: p.get('open') || null,
  };
}

export function toHash(s: RequestsState): string {
  const p = new URLSearchParams();
  if (s.view !== 'pending') p.set('view', s.view);
  if (s.q) p.set('q', s.q);
  if (s.user) p.set('user', s.user);
  if (s.type) p.set('type', s.type);
  if (s.added) p.set('added', s.added);
  if (s.sort) { p.set('sort', s.sort); if (s.order !== 'desc') p.set('order', s.order); }
  if (s.page !== 1) p.set('page', String(s.page));
  if (s.perPage !== 50) p.set('per_page', String(s.perPage));
  if (s.open) p.set('open', s.open);
  const q = p.toString();
  return q ? `#requests?${q}` : '#requests';
}

export function toQuery(s: RequestsState): Record<string, string> {
  return { view: s.view, q: s.q, user: s.user, type: s.type, added: s.added, sort: s.sort, order: s.order,
    page: String(s.page), per_page: String(s.perPage) };
}
