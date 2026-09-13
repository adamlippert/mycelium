import { describe, it, expect } from 'vitest';
import { formatCountdown, formatLatency, relativeAge } from './format';

describe('format helpers', () => {
  it('formatCountdown never reads "0 min" for a positive remainder', () => {
    expect(formatCountdown(0)).toBe('now');
    expect(formatCountdown(59)).toBe('under 1 min');
    expect(formatCountdown(60)).toBe('1 min');
    expect(formatCountdown(42 * 60 + 30)).toBe('42 min');
    expect(formatCountdown(65 * 60)).toBe('1 h 05 min');
  });
  it('formatLatency', () => {
    expect(formatLatency(null)).toBe('-');
    expect(formatLatency(412.6)).toBe('413 ms');
    expect(formatLatency(1500)).toBe('1.5 s');
  });
  it('relativeAge', () => {
    expect(relativeAge(30)).toBe('1 min');
    expect(relativeAge(7200)).toBe('2 h');
    expect(relativeAge(90000)).toBe('1 d 1 h');
  });
});
