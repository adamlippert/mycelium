import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { SettingsField, SetupSchema } from '../api';
import Setup from './Setup';

const apiMocks = vi.hoisted(() => ({ setupSchema: vi.fn(), setupTest: vi.fn(), setupPicker: vi.fn(), createUser: vi.fn() }));
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});

function schema(over: Partial<SetupSchema> = {}): SetupSchema {
  return {
    steps: [
      { id: 'welcome', title: 'Welcome', intro: 'Pick how this runs.', keys: ['LITE_MODE'], lite: true },
      { id: 'torbox', title: 'TorBox', intro: 'The one required key.', keys: ['TORBOX_API_KEY'], lite: true },
      { id: 'zilean', title: 'Zilean', intro: 'Optional index.', keys: ['ZILEAN_ENABLED', 'ZILEAN_URL'], lite: false },
    ],
    fields: [
      f({ key: 'LITE_MODE', label: 'Lite mode', kind: 'bool', value: false, hot_reload: false }),
      f({ key: 'TORBOX_API_KEY', label: 'TorBox API key', kind: 'secret', required: true, value: false, test: 'torbox' }),
      f({ key: 'ZILEAN_ENABLED', label: 'Use Zilean', kind: 'bool', value: false }),
      f({ key: 'ZILEAN_URL', label: 'Zilean URL', kind: 'url', depends_on: 'ZILEAN_ENABLED', test: 'zilean', value: '' }),
    ],
    needs_first_admin: false,
    ...over,
  };
}

function setCsrfMeta(value: string) {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  const meta = document.createElement('meta');
  meta.setAttribute('name', 'csrf-token');
  meta.setAttribute('content', value);
  document.head.appendChild(meta);
}

const next = () => userEvent.click(screen.getByRole('button', { name: /continue|finish/i }));

beforeEach(() => {
  vi.clearAllMocks();
  setCsrfMeta('test-csrf-token');
  apiMocks.setupSchema.mockResolvedValue(schema());
  vi.spyOn(window, 'alert').mockImplementation(() => {});
});
afterEach(() => {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  vi.restoreAllMocks();
});

describe('Setup', () => {
  it('renders the steps from the schema, first step first, with the rail', async () => {
    render(<Setup />);
    expect(await screen.findByRole('heading', { name: 'Welcome' })).toBeInTheDocument();
    expect(screen.getByText('Pick how this runs.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Lite mode' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('Lite mode hides the non-lite steps and the rail shrinks', async () => {
    render(<Setup />);
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Lite mode' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    await next();
    await userEvent.type(screen.getByLabelText('TorBox API key'), 'tb');
    await next();
    expect(screen.getByRole('heading', { name: /all set/i })).toBeInTheDocument();
  });

  it('Continue is disabled while a required field is blank, unless it is already set', async () => {
    render(<Setup />);
    await next();
    expect(await screen.findByRole('heading', { name: 'TorBox' })).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: /continue/i });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByLabelText('TorBox API key'), 'tb');
    expect(btn).toBeEnabled();
  });

  it('a required secret that is already set does not block', async () => {
    apiMocks.setupSchema.mockResolvedValue(schema({
      fields: schema().fields.map((x) => (x.key === 'TORBOX_API_KEY' ? { ...x, value: true } : x)),
    }));
    render(<Setup />);
    await next();
    expect(await screen.findByRole('heading', { name: 'TorBox' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled();
  });

  it('a dependent field appears when its toggle flips and Test posts the typed values through the setup API', async () => {
    apiMocks.setupTest.mockResolvedValue({ ok: true, message: 'Zilean answered HTTP 200' });
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    expect(await screen.findByRole('heading', { name: 'Zilean' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Zilean URL')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Use Zilean' }));
    await userEvent.type(screen.getByLabelText('Zilean URL'), 'http://z');
    await userEvent.click(screen.getByRole('button', { name: 'Test Zilean' }));
    await waitFor(() => expect(apiMocks.setupTest).toHaveBeenCalledWith('zilean', { ZILEAN_URL: 'http://z' }));
    expect(await screen.findByText('Zilean answered HTTP 200')).toBeInTheDocument();
  });

  it('finishing posts only the changed keys, unprefixed, as form fields', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    await next();
    expect(await screen.findByRole('heading', { name: /all set/i })).toBeInTheDocument();
    await next();
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('/setup/save', expect.anything()));
    const init = fetchSpy.mock.calls.find((c) => c[0] === '/setup/save')![1] as RequestInit;
    const body = init.body as FormData;
    expect(body.get('TORBOX_API_KEY')).toBe('tb');
    expect(body.has('LITE_MODE')).toBe(false);
    expect(body.has('ZILEAN_ENABLED')).toBe(false);
    expect(init.headers).toMatchObject({ 'X-CSRFToken': 'test-csrf-token' });
  });

  it('collects an admin account before Done when the schema says so, and refuses mismatched passwords', async () => {
    apiMocks.setupSchema.mockResolvedValue(schema({ needs_first_admin: true }));
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    await next();
    expect(await screen.findByRole('heading', { name: /create your admin account/i })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^username$/i), 'adam');
    await userEvent.type(screen.getByLabelText(/^password$/i), 'hunter2');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'hunter3');
    await next();
    expect(await screen.findByRole('heading', { name: /all set/i })).toBeInTheDocument();
    await next();
    expect(window.alert).toHaveBeenCalledWith(expect.stringMatching(/do not match/i));
    expect(fetchSpy).not.toHaveBeenCalledWith('/setup/save', expect.anything());
  });
});
