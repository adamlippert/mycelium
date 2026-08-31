import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import FilterRules from './FilterRules';

const CATEGORIES = [
  'RESOLUTION', 'SOURCE', 'ENCODE', 'VISUAL_TAG', 'AUDIO_TAG', 'AUDIO_CHANNELS', 'LANGUAGE',
];
const RESOLUTION_OPTIONS = ['2160p', '1080p', '720p', '480p', 'unknown'];

function settingsFixture() {
  const items: Array<{ key: string; value: unknown; kind: string; options: string[] | null }> = [];
  CATEGORIES.forEach((prefix) => {
    const options = prefix === 'RESOLUTION' ? RESOLUTION_OPTIONS : ['a', 'b', 'c'];
    items.push({ key: `${prefix}_PREFERRED`, value: prefix === 'RESOLUTION' ? ['2160p'] : [], kind: 'list', options });
    items.push({ key: `${prefix}_EXCLUDED`, value: [], kind: 'list', options });
    items.push({ key: `${prefix}_REQUIRED`, value: [], kind: 'list', options });
    items.push({ key: `${prefix}_INCLUDED`, value: [], kind: 'list', options });
  });
  CATEGORIES.forEach((prefix) => {
    items.push({ key: `${prefix}_STRICT`, value: false, kind: 'bool', options: null });
  });
  return {
    groups: [{ id: 'filter_rules', title: 'Filtering rules', items }],
    hot_reload: [],
  };
}

const apiMocks = vi.hoisted(() => ({
  settings: vi.fn(),
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
  return render(<QueryClientProvider client={qc}><FilterRules /></QueryClientProvider>);
}

describe('FilterRules tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.settings.mockResolvedValue(settingsFixture());
  });

  it('renders all seven category panels from the settings payload', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('RESOLUTION')).toBeInTheDocument();
    });
    expect(screen.getByText('SOURCE')).toBeInTheDocument();
    expect(screen.getByText('ENCODE')).toBeInTheDocument();
    expect(screen.getByText('VISUAL TAG')).toBeInTheDocument();
    expect(screen.getByText('AUDIO TAG')).toBeInTheDocument();
    expect(screen.getByText('AUDIO CHANNELS')).toBeInTheDocument();
    expect(screen.getByText('LANGUAGE')).toBeInTheDocument();
  });

  it('adding a value via the dropdown appends a chip', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('RESOLUTION')).toBeInTheDocument());

    const excludedRow = screen
      .getAllByRole('combobox')
      .find((el) => el.getAttribute('aria-label')?.includes('excluded value to resolution'));
    expect(excludedRow).toBeTruthy();

    await userEvent.selectOptions(excludedRow as HTMLElement, '720p');

    await waitFor(() => {
      expect(screen.getByText('720p')).toBeInTheDocument();
    });
  });

  it('the Included row shows the standing warning', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('RESOLUTION')).toBeInTheDocument());
    const warnings = screen.getAllByText(/overrides every other rule in every category/i);
    // one per category panel
    expect(warnings.length).toBe(CATEGORIES.length);
  });

  it('save serializes a changed category into setting_RESOLUTION_PREFERRED form data', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('', { status: 302 }),
    );

    renderIt();
    await waitFor(() => expect(screen.getByText('RESOLUTION')).toBeInTheDocument());

    const addSelect = screen
      .getAllByRole('combobox')
      .find((el) => el.getAttribute('aria-label')?.includes('preferred value to resolution')) as HTMLElement;
    await userEvent.selectOptions(addSelect, '1080p');

    await userEvent.click(screen.getByRole('button', { name: /save all/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find(([url]) => String(url).includes('/ui/settings'));
    expect(call).toBeTruthy();
    const init = call![1] as RequestInit;
    const body = String(init.body);
    expect(body).toContain('setting_RESOLUTION_PREFERRED=2160p%2C1080p');

    fetchSpy.mockRestore();
  });
});
