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

function setMeta(name: string, value: string) {
  document.head.querySelectorAll(`meta[name="${name}"]`).forEach((m) => m.remove());
  const meta = document.createElement('meta');
  meta.setAttribute('name', name);
  meta.setAttribute('content', value);
  document.head.appendChild(meta);
}

/** Walk the wizard from Welcome to its final pane. Step 1 refuses to advance
 * without a TorBox key, so fill that in on the way past. */
async function advanceToEnd() {
  const next = () => userEvent.click(screen.getByRole('button', { name: /continue/i }));
  await next(); // Welcome -> TorBox
  await userEvent.type(screen.getByLabelText(/torbox api key/i), 'tb-test-key');
  for (let i = 0; i < 10; i += 1) await next(); // through the content steps
}

describe('Setup first-admin step', () => {
  beforeEach(() => {
    // jsdom has no window.alert, and the wizard uses it for validation.
    vi.spyOn(window, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    document.head.querySelectorAll('meta[name="needs-first-admin"]').forEach((m) => m.remove());
  });

  it('is absent when the install already has a way in', async () => {
    setMeta('needs-first-admin', 'false');
    render(<Setup />);

    await advanceToEnd();

    expect(screen.getByRole('heading', { name: /all set/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/^username$/i)).not.toBeInTheDocument();
  });

  it('collects an admin account before Done when nothing can log in', async () => {
    setMeta('needs-first-admin', 'true');
    render(<Setup />);

    await advanceToEnd();

    expect(
      screen.getByRole('heading', { name: /create your admin account/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^username$/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByRole('heading', { name: /all set/i })).toBeInTheDocument();
  });

  it('refuses to finish with mismatched passwords', async () => {
    setMeta('needs-first-admin', 'true');
    const alert = window.alert as unknown as ReturnType<typeof vi.fn>;
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<Setup />);

    await advanceToEnd();
    await userEvent.type(screen.getByLabelText(/^username$/i), 'adam');
    await userEvent.type(screen.getByLabelText(/^password$/i), 'hunter2');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'hunter3');
    await userEvent.click(screen.getByRole('button', { name: /continue/i }));
    await userEvent.click(screen.getByRole('button', { name: /finish|go to dashboard|continue/i }));

    expect(alert).toHaveBeenCalledWith(expect.stringMatching(/do not match/i));
    expect(fetchSpy).not.toHaveBeenCalledWith('/setup/save', expect.anything());
  });
});
