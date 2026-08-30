import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Icon, ICON_NAMES } from './icons';

describe('Icon', () => {
  it('renders every name as an svg with path data', () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      const svg = container.querySelector('svg');
      expect(svg, `${name} rendered no svg`).not.toBeNull();
      expect(svg!.querySelector('path')?.getAttribute('d'), `${name} has no path data`).toBeTruthy();
    }
  });

  it('covers exactly the eleven navigable screens', () => {
    expect([...ICON_NAMES].sort()).toEqual([
      'admin', 'discover', 'library', 'login', 'manual', 'requests',
      'search', 'settings', 'setup', 'wanted', 'watchlist',
    ]);
  });

  it('inherits colour so the active nav state can tint it', () => {
    const { container } = render(<Icon name="discover" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('currentColor');
  });

  it('passes className through for sizing', () => {
    const { container } = render(<Icon name="library" className="w-4 h-4" />);
    expect(container.querySelector('svg')).toHaveClass('w-4', 'h-4');
  });
});
