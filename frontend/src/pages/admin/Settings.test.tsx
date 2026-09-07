import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Settings from './Settings';

function settingsFixture() {
  return {
    groups: [
      {
        id: 'g1',
        title: 'Group One',
        items: [
          { key: 'BOOL_KEY', value: true, kind: 'bool', options: null, overridden: false, hot_reload: true },
        ],
      },
      {
        id: 'g2',
        title: 'Group Two',
        items: [
          { key: 'ENUM_KEY', value: 'a', kind: 'enum', options: ['a', 'b'], overridden: false, hot_reload: false },
        ],
      },
      {
        id: 'arr_import',
        title: 'Radarr / Sonarr',
        items: [
          { key: 'RADARR_URL', value: 'http://r.test', kind: 'str', options: null, overridden: false, hot_reload: true },
          { key: 'RADARR_API_KEY', value: 'saved', kind: 'str', options: null, overridden: false, hot_reload: true },
          { key: 'RADARR_ROOT_FOLDER', value: '', kind: 'str', options: null, overridden: false, hot_reload: true },
          { key: 'SONARR_ROOT_FOLDER', value: '/tv', kind: 'str', options: null, overridden: false, hot_reload: true },
        ],
      },
      {
        id: 'filter_rules',
        title: 'Filtering rules',
        items: [
          { key: 'RESOLUTION_PREFERRED', value: [], kind: 'list', options: ['2160p'], overridden: false, hot_reload: false },
        ],
      },
    ],
    hot_reload: [],
  };
}

const apiMocks = vi.hoisted(() => ({
  settings: vi.fn(),
  genreTabsConfig: vi.fn(),
  genres: vi.fn(),
  setGenreTabsConfig: vi.fn(),
  autoAddNow: vi.fn(),
  arrTest: vi.fn(),
  arrRootFolders: vi.fn(),
}));

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: { ...actual.api, ...apiMocks },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Settings /></QueryClientProvider>);
}

describe('Settings tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.settings.mockResolvedValue(settingsFixture());
    apiMocks.genreTabsConfig.mockResolvedValue({ tabs: [] });
    apiMocks.genres.mockResolvedValue({ genres: [] });
    apiMocks.setGenreTabsConfig.mockResolvedValue({ ok: true });
    apiMocks.autoAddNow.mockResolvedValue({ ok: true, message: 'started' });
  });

  it('renders every group except filter_rules', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('Group One')).toBeInTheDocument();
    });
    expect(screen.getByText('Group Two')).toBeInTheDocument();
    expect(screen.queryByText('Filtering rules')).not.toBeInTheDocument();
  });

  it('the arr group has Test buttons that post the URL and key as typed', async () => {
    apiMocks.arrTest.mockResolvedValue({ ok: true, version: '5.1.0.9999' });
    renderIt();
    await waitFor(() => expect(screen.getByText('Radarr / Sonarr')).toBeInTheDocument());
    const url = screen.getByRole('textbox', { name: 'RADARR_URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new.test');
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.arrTest).toHaveBeenCalledWith('radarr', { url: 'http://new.test', api_key: '' }));
    expect(await screen.findByText('✓ Radarr 5.1.0.9999 reachable')).toBeInTheDocument();
  });

  it('a failed Test shows the reason', async () => {
    apiMocks.arrTest.mockResolvedValue({ ok: false, error: 'Sonarr did not answer, or refused the API key' });
    renderIt();
    await waitFor(() => expect(screen.getByText('Radarr / Sonarr')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Test Sonarr' }));
    expect(await screen.findByText('✗ Sonarr did not answer, or refused the API key')).toBeInTheDocument();
  });

  it('root folders are a dropdown filled from the arr, and the pick is what gets saved', async () => {
    apiMocks.arrRootFolders.mockResolvedValue({
      ok: true,
      folders: [{ path: '/movies', free_space: 5 * 1024 ** 3 }, { path: '/mnt/more', free_space: null }],
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(new Response('', { status: 302 }));
    renderIt();
    await waitFor(() => expect(screen.getByText('Radarr / Sonarr')).toBeInTheDocument());

    const radarrPick = screen.getByRole('combobox', { name: 'RADARR_ROOT_FOLDER' });
    expect(radarrPick).toHaveValue('');
    // The saved Sonarr value is offered even before its folders are loaded.
    expect(screen.getByRole('combobox', { name: 'SONARR_ROOT_FOLDER' })).toHaveValue('/tv');

    await userEvent.click(screen.getAllByRole('button', { name: 'Load folders' })[0]);
    await waitFor(() => expect(apiMocks.arrRootFolders).toHaveBeenCalledWith('radarr', { url: 'http://r.test', api_key: '' }));
    expect(await screen.findByRole('option', { name: '/movies (5 GB free)' })).toBeInTheDocument();
    await userEvent.selectOptions(radarrPick, '/mnt/more');

    await userEvent.click(screen.getByRole('button', { name: /save all/i }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find(([u]) => String(u).includes('/ui/settings'));
    expect(String((call![1] as RequestInit).body)).toContain('setting_RADARR_ROOT_FOLDER=%2Fmnt%2Fmore');
    fetchSpy.mockRestore();
  });

  it('renders a checkbox for the bool item and a combobox for the enum item', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('Group One')).toBeInTheDocument());
    expect(screen.getByRole('checkbox', { name: 'BOOL_KEY' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'ENUM_KEY' })).toBeInTheDocument();
  });

  it('Save all posts form-encoded setting_<KEY> for both items', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('', { status: 302 }),
    );

    renderIt();
    await waitFor(() => expect(screen.getByText('Group One')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /save all/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/ui/settings'));
    expect(call).toBeTruthy();
    const init = call![1] as RequestInit;
    const body = String(init.body);
    expect(body).toContain('setting_BOOL_KEY=true');
    expect(body).toContain('setting_ENUM_KEY=a');

    fetchSpy.mockRestore();
  });

  it('shows the Legacy password card', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('Group One')).toBeInTheDocument());
    expect(screen.getByLabelText(/legacy password/i)).toBeInTheDocument();
  });

  it('posts the legacy password field to /ui/set-password', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('', { status: 302 }),
    );

    renderIt();
    await waitFor(() => expect(screen.getByText('Group One')).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText(/legacy password/i), 'newpassword');
    await userEvent.click(screen.getByRole('button', { name: /update legacy password/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/ui/set-password'));
    expect(call).toBeTruthy();
    const init = call![1] as RequestInit;
    expect(String(init.body)).toContain('password=newpassword');

    fetchSpy.mockRestore();
  });
});
