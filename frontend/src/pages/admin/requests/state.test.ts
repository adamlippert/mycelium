import { describe, it, expect } from 'vitest';
import { DEFAULT_STATE, parseHash, toHash, toQuery } from './state';

describe('requests hash state', () => {
  it('round-trips and drops defaults', () => {
    const s = { ...DEFAULT_STATE, view: 'denied', q: 'heat', user: '3', page: 2, open: 'tt1' };
    const h = toHash(s);
    expect(h).toBe('#requests?view=denied&q=heat&user=3&page=2&open=tt1');
    expect(parseHash(h)).toEqual(s);
    expect(toHash(DEFAULT_STATE)).toBe('#requests');
    expect(parseHash('#library?view=queue')).toEqual(DEFAULT_STATE);
  });
  it('ignores junk', () => {
    const s = parseHash('#requests?view=bogus&type=cartoon&added=1y&sort=nope&order=up&page=0');
    expect(s).toEqual(DEFAULT_STATE);
  });
  it('serialises to query params', () => {
    expect(toQuery({ ...DEFAULT_STATE, view: 'pending', user: '3' })).toEqual({
      view: 'pending', q: '', user: '3', type: '', added: '', sort: '', order: 'desc', page: '1', per_page: '50',
    });
  });
});
