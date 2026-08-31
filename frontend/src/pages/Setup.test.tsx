import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import Setup from './Setup';

function setCsrfMeta(value: string) {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  const meta = document.createElement('meta');
  meta.setAttribute('name', 'csrf-token');
  meta.setAttribute('content', value);
  document.head.appendChild(meta);
}

beforeEach(() => {
  setCsrfMeta('test-csrf-token');
});

afterEach(() => {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  vi.restoreAllMocks();
});

describe('Setup', () => {
  it('renders the Welcome step', () => {
    render(<Setup />);
    expect(screen.getByRole('heading', { name: /welcome/i })).toBeInTheDocument();
  });

  it('advances to the TorBox step (setup.html\'s second section) on Continue', async () => {
    render(<Setup />);
    await userEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByRole('heading', { name: /^torbox$/i })).toBeInTheDocument();
  });

  it('shows ten steps in the step rail', () => {
    render(<Setup />);
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
  });

  it('a Test button posts FormData to /setup/test/torbox and renders the mocked ok detail', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true, detail: 'HTTP 200' }), { status: 200 }),
    );

    render(<Setup />);
    await userEvent.click(screen.getByRole('button', { name: /continue/i }));
    await userEvent.type(screen.getByLabelText(/torbox api key/i), 'tb-secret');
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    expect(await screen.findByText(/HTTP 200/)).toBeInTheDocument();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/setup/test/torbox');
    expect((init as RequestInit).method).toBe('POST');
    expect((init as RequestInit).headers).toMatchObject({ 'X-CSRFToken': 'test-csrf-token' });
    const body = (init as RequestInit).body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('TORBOX_API_KEY')).toBe('tb-secret');
  });
});
