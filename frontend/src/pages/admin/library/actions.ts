import { api } from '../../../api';
import type { LibraryDetail } from '../../../api';

type Result = { ok: boolean; message: string };
const path = (imdb: string, tail: string) => `/ui/api/library/${imdb}/${tail}`;

export const ACTIONS = {
  retry: async (d: LibraryDetail): Promise<Result> => { const r = await api.retryRequest(d.request.id); return { ok: r.ok, message: r.ok ? 'retry started' : 'retry failed' }; },
  reresolve: async (d: LibraryDetail): Promise<Result> => {
    if (!d.items.length) return { ok: false, message: 'no stream to re-resolve' };
    const results = await Promise.all(d.items.map((i) => api.reResolve(i.token)));
    const n = results.filter((r) => r.resolved).length;
    return { ok: n > 0, message: `${n} of ${results.length} resolved` };
  },
  mirror: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'mirror')),
  unmirror: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'unmirror')),
  purge: async (d: LibraryDetail): Promise<Result> => { await api.purgeRequest(d.request.id); return { ok: true, message: 'removed from the library' }; },
  forget: async (d: LibraryDetail): Promise<Result> => { await api.deleteRequest(d.request.id); return { ok: true, message: 'request forgotten, files kept' }; },
  blacklistCurrent: (d: LibraryDetail) => d.request.info_hash
    ? api.libraryAction(`/ui/api/library/hash/${d.request.info_hash}/blacklist`)
    : Promise.resolve({ ok: false, message: 'no current hash' }),
  dropRetry: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'drop-retry')),
  retryNow: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'retry-now')),
  resetPlayability: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'playability/reset')),
  recheckSeries: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'recheck-series')),
  retryEpisode: (d: LibraryDetail, s: number, e: number) => api.libraryAction(path(d.request.imdb_id, `episodes/${s}/${e}/retry`)),
  blacklist: (hash: string) => api.libraryAction(`/ui/api/library/hash/${hash}/blacklist`),
  unblacklist: (hash: string) => api.libraryAction(`/ui/api/library/hash/${hash}/unblacklist`),
  saveOverride: (d: LibraryDetail, body: unknown) => api.libraryAction(path(d.request.imdb_id, 'override'), 'POST', body),
  clearOverride: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'override'), 'DELETE'),
};
