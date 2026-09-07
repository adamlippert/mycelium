import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Settings from './Settings';

function field(over: Record<string, unknown>) {
  return {
    key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null, min: null, max: null,
    advanced: false, depends_on: null, test: null, picker: null, component: null, readonly: false, value: '', overridden: false, hot_reload: true,
    ...over,
  };
}

function schemaFixture() {
  return {
    sections: [
      { id: 'mode', title: 'Mode', description: 'How it runs.', icon: 'x', fields: [
        field({ key: 'LITE_MODE', kind: 'bool', value: false, hot_reload: false, label: 'Lite mode' }),
        field({ key: 'CATBOX_MODE', kind: 'bool', value: true, label: 'Catbox mode', hot_reload: false }),
      ] },
      { id: 'jellyfin', title: 'Jellyfin', description: 'The player.', icon: 'x', fields: [
        field({ key: 'JELLYFIN_URL', kind: 'url', label: 'Jellyfin URL', value: 'http://jf' , test: 'jellyfin' }),
        field({ key: 'JELLYFIN_REFRESH_DELAY_SEC', kind: 'int', label: 'Refresh delay', advanced: true, value: 5 }),
      ] },
      { id: 'intervals', title: 'Intervals', description: 'Timers.', icon: 'x', fields: [
        field({ key: 'CLEANUP_INTERVAL_HOURS', kind: 'int', label: 'Cleanup', advanced: true, value: 24, hot_reload: false }),
      ] },
    ],
    hot_reload: [],
  };
}

const apiMocks = vi.hoisted(() => ({
  settingsSchema: vi.fn(), saveSettings: vi.fn(), settingsTest: vi.fn(), settingsPicker: vi.fn(),
  genreTabsConfig: vi.fn(), genres: vi.fn(), setGenreTabsConfig: vi.fn(), autoAddNow: vi.fn(),
  setLegacyPassword: vi.fn(), webhookSecret: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Settings /></QueryClientProvider>);
}

describe('Settings shell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    apiMocks.settingsSchema.mockResolvedValue(schemaFixture());
    apiMocks.saveSettings.mockResolvedValue(undefined);
    apiMocks.genreTabsConfig.mockResolvedValue({ tabs: [] });
    apiMocks.genres.mockResolvedValue({ genres: [] });
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'abc' });
  });

  it('lists sections in a sidebar and shows the first one', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByRole('heading', { name: 'Mode' })).toBeInTheDocument();
    expect(screen.getByText('Lite mode')).toBeInTheDocument();
  });

  it('switches sections and remembers the Simple/Advanced choice', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Refresh delay')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    expect(screen.getByLabelText('Refresh delay')).toBeInTheDocument();
    expect(localStorage.getItem('mycelium.settings.advanced')).toBe('true');
  });

  it('an all-advanced section explains itself in simple mode', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Intervals/ }));
    expect(screen.getByText(/Everything here is an advanced setting/)).toBeInTheDocument();
  });

  it('search narrows the sidebar to matching sections and opens the first match', async () => {
    renderIt();
    await screen.findByRole('navigation', { name: 'Settings sections' });
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search settings' }), 'refresh');
    const nav = screen.getByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument();
  });

  it('counts unsaved changes, warns about restart fields and posts the flattened values', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    const url = screen.getByRole('textbox', { name: 'Jellyfin URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new');
    expect(screen.getByText('1 unsaved change')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Mode/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Catbox mode' }));
    expect(screen.getByText('2 unsaved changes')).toBeInTheDocument();
    expect(screen.getByText(/restart the container after saving/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.saveSettings).toHaveBeenCalledWith({
      setting_JELLYFIN_URL: 'http://new', setting_CATBOX_MODE: 'false',
    }));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
  });

  it('refetches the schema after save so overridden/"env" badges go stale-free', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    expect(screen.getByText('env')).toBeInTheDocument();

    const url = screen.getByRole('textbox', { name: 'Jellyfin URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new');

    const refreshed = schemaFixture();
    refreshed.sections[1].fields[0] = { ...refreshed.sections[1].fields[0], value: 'http://new', overridden: true };
    apiMocks.settingsSchema.mockResolvedValueOnce(refreshed);

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.settingsSchema).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('env')).not.toBeInTheDocument());
  });

  it('Save starts disabled and enables after an edit', async () => {
    renderIt();
    await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Catbox mode' }));
    expect(screen.getByRole('button', { name: 'Save' })).not.toBeDisabled();
  });

  it('defaults to Simple pressed and Advanced unpressed', async () => {
    renderIt();
    await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(screen.getByRole('button', { name: 'Simple' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Advanced' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('honours a pre-set Advanced preference from localStorage', async () => {
    localStorage.setItem('mycelium.settings.advanced', 'true');
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    expect(screen.getByRole('button', { name: 'Advanced' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Refresh delay')).toBeInTheDocument();
  });
});
