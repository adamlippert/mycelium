import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p: string) => readFileSync(resolve(__dirname, p), 'utf8');
const tokens = () => read('./tokens.css');
const tailwind = () => read('../../tailwind.config.js');
const indexCss = () => read('../index.css');

describe('the palette', () => {
  it('uses the new brand purple, not the old indigo', () => {
    expect(tailwind()).toContain('#6152df');
    expect(tailwind()).not.toContain('#6366f1');
  });

  it('drops the retired tokens', () => {
    // These are unquoted keys in the current config, so matching the bare
    // name in quotes would pass even if the key survived. Match the key.
    const config = tailwind();
    for (const retired of ['accent-2', 'teal', 'mint', 'amber', 'info']) {
      const key = new RegExp(`(^|\\s|')${retired}'?\\s*:`, 'm');
      expect(config, `${retired} is still defined`).not.toMatch(key);
    }
  });

  it('sets the page and sidebar grounds', () => {
    expect(tailwind()).toContain('#070707');
    expect(tailwind()).toContain('#0b0b0b');
  });
});

describe('the pill tokens', () => {
  const STATES = ['ready', 'materializing', 'queued', 'failed', 'lazy'];

  it('defines a background, foreground and border for every state', () => {
    const css = tokens();
    for (const s of STATES) {
      expect(css).toContain(`--pill-${s}-bg:`);
      expect(css).toContain(`--pill-${s}-fg:`);
      expect(css).toContain(`--pill-${s}-border:`);
    }
  });

  it('composites the pill backgrounds over the dark ground', () => {
    // Flat hex here would look wrong on a card that is not the page colour.
    expect(tokens()).toMatch(/--pill-ready-bg:\s*rgba\(/);
  });
});

describe('fonts', () => {
  it('are self-hosted, never fetched from Google', () => {
    const css = indexCss();
    expect(css).toContain('@fontsource/inter');
    expect(css).toContain('@fontsource/jetbrains-mono');
    expect(css).not.toContain('fonts.googleapis.com');
    expect(css).not.toContain('fonts.gstatic.com');
  });
});
