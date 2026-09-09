import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach } from 'vitest';
import { ReferenceSection } from './ReferenceSection';

describe('ReferenceSection', () => {
  beforeEach(() => localStorage.clear());

  it('is closed by default and renders its body only once opened', async () => {
    let opened = false;
    render(<ReferenceSection id="metrics" title="Metrics, 30 days" hint="latency">{(open) => { opened = open; return <p>body</p>; }}</ReferenceSection>);
    expect(opened).toBe(false);
    await userEvent.click(screen.getByText('Metrics, 30 days'));
    expect(opened).toBe(true);
    expect(localStorage.getItem('mycelium.overview.metrics')).toBe('1');
  });

  it('remembers an open state', () => {
    localStorage.setItem('mycelium.overview.folders', '1');
    let opened = false;
    render(<ReferenceSection id="folders" title="Top folders" hint="">{(open) => { opened = open; return null; }}</ReferenceSection>);
    expect(opened).toBe(true);
  });
});
