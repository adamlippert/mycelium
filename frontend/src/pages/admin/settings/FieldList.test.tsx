import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SettingsField, SettingsSection } from '../../../api';
import { FieldList, SERVICE_LABEL } from './FieldList';
import { SECRET_CLEARED } from './visibility';

const apiMocks = vi.hoisted(() => ({ settingsTest: vi.fn(), setupTest: vi.fn(), settingsPicker: vi.fn(), setupPicker: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});
const FIELDS = [
  f({ key: 'RADARR_URL', label: 'Radarr URL', kind: 'url', test: 'radarr', value: 'http://r.test' }),
  f({ key: 'RADARR_ROOT_FOLDER', label: 'Radarr root folder', kind: 'path', picker: 'radarr_root_folders', value: '' }),
];
const SECTION: SettingsSection = { id: 's', title: 'S', description: 'd', icon: 'x', fields: FIELDS };

function renderIt(endpoint: 'settings' | 'setup') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const values = { RADARR_URL: 'http://r.test', RADARR_ROOT_FOLDER: '' };
  return render(
    <QueryClientProvider client={qc}>
      <FieldList fields={FIELDS} sections={[SECTION]} values={values} onChange={() => {}} advanced endpoint={endpoint} />
    </QueryClientProvider>,
  );
}

describe('FieldList endpoint', () => {
  beforeEach(() => vi.clearAllMocks());

  it('routes Test and Load through the settings API by default', async () => {
    apiMocks.settingsTest.mockResolvedValue({ ok: true, message: 'Radarr 5' });
    apiMocks.settingsPicker.mockResolvedValue({ ok: true, options: [{ value: '/movies', label: '/movies' }] });
    renderIt('settings');
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.settingsTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://r.test' }));
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    await waitFor(() => expect(apiMocks.settingsPicker).toHaveBeenCalled());
    expect(apiMocks.setupTest).not.toHaveBeenCalled();
  });

  it('routes them through the setup API when told to', async () => {
    apiMocks.setupTest.mockResolvedValue({ ok: true, message: 'Radarr 5' });
    apiMocks.setupPicker.mockResolvedValue({ ok: true, options: [] });
    renderIt('setup');
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.setupTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://r.test' }));
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    await waitFor(() => expect(apiMocks.setupPicker).toHaveBeenCalledWith('radarr_root_folders', { RADARR_URL: 'http://r.test' }));
    expect(apiMocks.settingsTest).not.toHaveBeenCalled();
  });
});

describe('SERVICE_LABEL', () => {
  it('names the Torznab scrapers', () => {
    expect(SERVICE_LABEL.comet).toBe('Comet');
    expect(SERVICE_LABEL.mediafusion).toBe('MediaFusion');
  });
});

describe('secret field Clear button', () => {
  beforeEach(() => vi.clearAllMocks());

  function renderSecret(setValue: boolean, overridden: boolean, endpoint: 'settings' | 'setup' = 'settings') {
    const secretField = f({ key: 'TORBOX_API_KEY', label: 'TorBox API key', kind: 'secret', value: setValue, overridden });
    const section: SettingsSection = { id: 's', title: 'S', description: 'd', icon: 'x', fields: [secretField] };
    const onChange = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <FieldList fields={[secretField]} sections={[section]} values={{ TORBOX_API_KEY: '' }} onChange={onChange} advanced endpoint={endpoint} />
      </QueryClientProvider>,
    );
    return onChange;
  }

  it('offers a Clear button when the secret is set and stored in the database, and marks it cleared like a typed value', async () => {
    const onChange = renderSecret(true, true);
    const clear = screen.getByRole('button', { name: 'Clear TorBox API key' });
    await userEvent.click(clear);
    expect(onChange).toHaveBeenCalledWith('TORBOX_API_KEY', SECRET_CLEARED);
  });

  it('does not offer a Clear button when the secret is not set', () => {
    renderSecret(false, false);
    expect(screen.queryByRole('button', { name: 'Clear TorBox API key' })).not.toBeInTheDocument();
  });

  it('does not offer a Clear button when the secret is set but not overridden (comes from the environment)', () => {
    renderSecret(true, false);
    expect(screen.queryByRole('button', { name: 'Clear TorBox API key' })).not.toBeInTheDocument();
  });

  it('works the same through the setup wizard endpoint', async () => {
    const onChange = renderSecret(true, true, 'setup');
    await userEvent.click(screen.getByRole('button', { name: 'Clear TorBox API key' }));
    expect(onChange).toHaveBeenCalledWith('TORBOX_API_KEY', SECRET_CLEARED);
  });
});
