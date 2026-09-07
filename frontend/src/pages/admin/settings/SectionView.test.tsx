import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { SectionView } from './SectionView';
import { initialValues } from './visibility';

const apiMocks = vi.hoisted(() => ({ settingsTest: vi.fn(), settingsPicker: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});

const SECTION: SettingsSection = {
  id: 'arrs', title: 'Radarr / Sonarr', description: 'Mirror the library.', icon: 'x',
  fields: [
    f({ key: 'ARR_SYNC_ENABLED', label: 'Mirror the library', kind: 'bool', value: true }),
    f({ key: 'RADARR_URL', label: 'Radarr URL', kind: 'url', depends_on: 'ARR_SYNC_ENABLED', test: 'radarr', value: 'http://r.test' }),
    f({ key: 'RADARR_API_KEY', label: 'Radarr API key', kind: 'secret', depends_on: 'ARR_SYNC_ENABLED', test: 'radarr', value: true }),
    f({ key: 'RADARR_ROOT_FOLDER', label: 'Radarr root folder', kind: 'path', depends_on: 'ARR_SYNC_ENABLED', picker: 'radarr_root_folders', value: '' }),
    f({ key: 'ARR_SYNC_INTERVAL_MINUTES', label: 'Reconcile interval', kind: 'int', unit: 'minutes', advanced: true, hot_reload: false, value: 60 }),
    f({ key: 'SORT_ORDER', label: 'Sort order', kind: 'ordered', options: [{ value: 'a', label: 'a' }, { value: 'b', label: 'b' }], value: ['a'] }),
    f({ key: '__Note', label: 'Note', kind: 'custom', component: 'Note' }),
  ],
};

function Harness({ advanced = false, query = '' }: { advanced?: boolean; query?: string }) {
  const [values, setValues] = useState(initialValues([SECTION]));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <SectionView
        section={SECTION}
        sections={[SECTION]}
        values={values}
        onChange={(k, v) => setValues((p) => ({ ...p, [k]: v }))}
        advanced={advanced}
        query={query}
        custom={{ Note: () => <div>custom card</div> }}
      />
    </QueryClientProvider>
  );
}

describe('SectionView', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders label, help, the right control per kind, and the custom card', () => {
    render(<Harness />);
    expect(screen.getByText('Mirror the library')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Mirror the library' })).toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Radarr URL' })).toHaveValue('http://r.test');
    const secret = screen.getByLabelText('Radarr API key');
    expect(secret).toHaveAttribute('type', 'password');
    expect(secret).toHaveAttribute('placeholder', expect.stringContaining('already set'));
    expect(screen.getByRole('button', { name: 'Move a down' })).toBeInTheDocument();
    expect(screen.getByText('custom card')).toBeInTheDocument();
  });

  it('reveals a secret, hides advanced fields in simple mode and shows them in advanced', async () => {
    const { rerender } = render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Show Radarr API key' }));
    expect(screen.getByLabelText('Radarr API key')).toHaveAttribute('type', 'text');
    expect(screen.queryByLabelText('Reconcile interval')).not.toBeInTheDocument();
    rerender(<Harness advanced />);
    expect(screen.getByLabelText('Reconcile interval')).toHaveValue(60);
    expect(screen.getByText('minutes')).toBeInTheDocument();
    expect(screen.getByText('restart')).toBeInTheDocument();
  });

  it('hides dependent fields when the toggle goes off', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mirror the library' }));
    expect(screen.queryByRole('textbox', { name: 'Radarr URL' })).not.toBeInTheDocument();
  });

  it('dims fields that do not match the search', () => {
    render(<Harness query="root" />);
    expect(screen.getByTestId('field-RADARR_ROOT_FOLDER')).not.toHaveClass('opacity-40');
    expect(screen.getByTestId('field-RADARR_URL')).toHaveClass('opacity-40');
  });

  it('one Test button per service posts the typed values and shows the message', async () => {
    apiMocks.settingsTest.mockResolvedValue({ ok: true, message: 'Radarr 5.2.0, 12 movies' });
    render(<Harness />);
    const url = screen.getByRole('textbox', { name: 'Radarr URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new.test');
    expect(screen.getAllByRole('button', { name: 'Test Radarr' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.settingsTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://new.test', RADARR_API_KEY: '' }));
    expect(await screen.findByText('Radarr 5.2.0, 12 movies')).toBeInTheDocument();
    apiMocks.settingsTest.mockResolvedValue({ ok: false, message: 'Radarr refused the API key (HTTP 401)' });
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    expect(await screen.findByText('Radarr refused the API key (HTTP 401)')).toHaveClass('text-danger');
  });

  it('does not claim advanced fields are hidden when they are actually hidden by a failed dependency', () => {
    const gated: SettingsSection = {
      id: 'gated', title: 'Gated', description: 'Locked behind a toggle.', icon: 'x',
      fields: [
        f({ key: 'DEP_FIELD', label: 'Dependent field', kind: 'str', depends_on: 'TOGGLE' }),
        f({ key: 'ADV_FIELD', label: 'Advanced field', kind: 'str', advanced: true, depends_on: 'TOGGLE' }),
      ],
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <SectionView section={gated} sections={[gated]} values={{ TOGGLE: false }} onChange={() => {}} advanced={false} query="" custom={{}} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText(/Everything here is an advanced setting/)).not.toBeInTheDocument();
  });

  it('a picker loads options into a dropdown and keeps a text input on failure', async () => {
    apiMocks.settingsPicker.mockResolvedValue({ ok: true, options: [{ value: '/movies', label: '/movies (5 GB free)' }] });
    render(<Harness />);
    expect(screen.getByRole('textbox', { name: 'Radarr root folder' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    const pick = await screen.findByRole('combobox', { name: 'Radarr root folder' });
    await waitFor(() => expect(apiMocks.settingsPicker).toHaveBeenCalledWith('radarr_root_folders', { RADARR_URL: 'http://r.test', RADARR_API_KEY: '' }));
    await userEvent.selectOptions(pick, '/movies');
    expect(pick).toHaveValue('/movies');
    apiMocks.settingsPicker.mockResolvedValue({ ok: false, error: 'Radarr did not answer, or refused the API key' });
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    expect(await screen.findByText('Radarr did not answer, or refused the API key')).toBeInTheDocument();
  });
});
