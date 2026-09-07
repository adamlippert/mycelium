import { describe, it, expect } from 'vitest';
import { DEFAULT_STATE, parseHash, toHash, toQuery } from './state';

describe('library hash state', () => {
  it('round-trips through the hash and drops defaults', () => {
    const s = { ...DEFAULT_STATE, view: 'attention', q: 'heat', status: ['failed', 'wanted'], page: 3, open: 'tt1' };
    const h = toHash(s);
    expect(h).toBe('#library?view=attention&q=heat&status=failed%2Cwanted&page=3&open=tt1');
    expect(parseHash(h)).toEqual(s);
    expect(toHash(DEFAULT_STATE)).toBe('#library');
    expect(parseHash('#library')).toEqual(DEFAULT_STATE);
    expect(parseHash('#settings')).toEqual(DEFAULT_STATE);
  });
  it('ignores junk and clamps the page', () => {
    expect(parseHash('#library?view=bogus&page=-2&order=sideways').view).toBe('all');
    expect(parseHash('#library?page=-2').page).toBe(1);
    expect(parseHash('#library?order=sideways').order).toBe('desc');
  });
  it('turns state into query params with statuses repeated', () => {
    expect(toQuery({ ...DEFAULT_STATE, status: ['failed', 'wanted'], q: 'x' })).toEqual({
      view: 'all', q: 'x', status: ['failed', 'wanted'], type: '', problem: '', requester: '', added: '',
      sort: '', order: 'desc', page: '1', per_page: '50',
    });
  });
});
