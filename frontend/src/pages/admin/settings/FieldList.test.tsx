import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SettingsField, SettingsSection } from '../../../api';
import { FieldList } from './FieldList';

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
