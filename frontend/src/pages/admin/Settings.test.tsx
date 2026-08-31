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
