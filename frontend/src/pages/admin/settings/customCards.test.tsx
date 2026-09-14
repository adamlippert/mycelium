import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { FilterRulesLink, LegacyPassword, TorboxAccounts, WebhookSecret } from './customCards';

const apiMocks = vi.hoisted(() => ({
  setLegacyPassword: vi.fn(), webhookSecret: vi.fn(), rotateWebhookSecret: vi.fn(),
  torboxAccounts: vi.fn(), torboxAccountAdd: vi.fn(), torboxAccountUpdate: vi.fn(),
  torboxAccountDelete: vi.fn(), torboxAccountTest: vi.fn(),
}));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderWithClient(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{children}</QueryClientProvider>);
}

function HashProbe() {
  const location = useLocation();
  return <div data-testid="hash-probe">{location.hash}</div>;
}

const noop = { values: {}, onChange: () => {} };

describe('LegacyPassword', () => {
  beforeEach(() => vi.clearAllMocks());

  it('rejects a password under 6 characters without calling the api', async () => {
    renderWithClient(<LegacyPassword {...noop} />);
    await userEvent.type(screen.getByLabelText('Legacy password'), 'abc');
    await userEvent.click(screen.getByRole('button', { name: 'Update legacy password' }));
    expect(await screen.findByText('Password must be at least 6 characters')).toBeInTheDocument();
    expect(apiMocks.setLegacyPassword).not.toHaveBeenCalled();
  });

  it('saves a valid password and shows the confirmation', async () => {
    apiMocks.setLegacyPassword.mockResolvedValue({ ok: true });
    renderWithClient(<LegacyPassword {...noop} />);
    await userEvent.type(screen.getByLabelText('Legacy password'), 'secret-pw');
    await userEvent.click(screen.getByRole('button', { name: 'Update legacy password' }));
    expect(apiMocks.setLegacyPassword).toHaveBeenCalledWith('secret-pw');
    expect(await screen.findByText('Updated.')).toBeInTheDocument();
  });
});

describe('WebhookSecret', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the secret from the api in a readonly input', async () => {
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'abc' });
    renderWithClient(<WebhookSecret {...noop} />);
    const input = screen.getByLabelText('Webhook secret');
    await waitFor(() => expect(input).toHaveValue('abc'));
    expect(input).toHaveAttribute('readonly');
  });

  it('rotates after an inline confirm and shows the new secret with the grace window', async () => {
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'abc', source: 'auto', previous_valid_until: null });
    apiMocks.rotateWebhookSecret.mockImplementation(() => {
      apiMocks.webhookSecret.mockResolvedValue({ secret: 'xyz', source: 'auto', previous_valid_until: '2026-09-09T12:00:00Z' });
      return Promise.resolve({ secret: 'xyz', source: 'auto', previous_valid_until: '2026-09-09T12:00:00Z' });
    });
    renderWithClient(<WebhookSecret {...noop} />);
    await waitFor(() => expect(screen.getByLabelText('Webhook secret')).toHaveValue('abc'));
    await userEvent.click(screen.getByRole('button', { name: 'Rotate' }));
    expect(screen.getByText(/keeps working for 24 hours/)).toBeInTheDocument();
    expect(apiMocks.rotateWebhookSecret).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByLabelText('Webhook secret')).toHaveValue('xyz'));
    expect(apiMocks.rotateWebhookSecret).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Previous secret valid until/)).toBeInTheDocument();
    expect(screen.getByText(/^Rotated\./)).toBeInTheDocument();
    expect(screen.queryByText(/keeps working for 24 hours/)).not.toBeInTheDocument();
  });

  it('cancel closes the confirm without rotating', async () => {
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'abc', source: 'auto', previous_valid_until: null });
    renderWithClient(<WebhookSecret {...noop} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Rotate' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText(/keeps working for 24 hours/)).not.toBeInTheDocument();
    expect(apiMocks.rotateWebhookSecret).not.toHaveBeenCalled();
  });

  it('disables Rotate when the secret comes from the environment', async () => {
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'env-1', source: 'env', previous_valid_until: null });
    renderWithClient(<WebhookSecret {...noop} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rotate' })).toBeDisabled());
    expect(screen.getByText(/change WEBHOOK_SECRET there and restart/)).toBeInTheDocument();
  });
});

describe('TorboxAccounts', () => {
  beforeEach(() => vi.clearAllMocks());

  const accounts = [
    { id: 1, label: 'main', enabled: true, key_hint: 'ab12', items: 3,
      health: { rate_limited_until: null, auth_failed_at: null, budget_left: 60 } },
    { id: 2, label: 'second', enabled: true, key_hint: 'cd34', items: 1,
      health: { rate_limited_until: null, auth_failed_at: null, budget_left: 58 } },
  ];

  it('lists accounts with label, key hint and counts, and gives account 1 Test only', async () => {
    apiMocks.torboxAccounts.mockResolvedValue({ accounts });
    renderWithClient(<TorboxAccounts {...noop} />);
    expect(await screen.findByText('main')).toBeInTheDocument();
    expect(screen.getByText('key ending ab12')).toBeInTheDocument();
    expect(screen.getByText('3 titles, 60 adds left')).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
    expect(screen.getByText('key ending cd34')).toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    const mainRow = rows.find((r) => r.textContent?.includes('main'));
    const secondRow = rows.find((r) => r.textContent?.includes('second'));
    expect(mainRow).toBeTruthy();
    expect(secondRow).toBeTruthy();
    expect(within(mainRow as HTMLElement).getByRole('button', { name: 'Test' })).toBeInTheDocument();
    expect(within(mainRow as HTMLElement).queryByRole('button', { name: 'Disable' })).not.toBeInTheDocument();
    expect(within(mainRow as HTMLElement).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    expect(within(secondRow as HTMLElement).getByRole('button', { name: 'Test' })).toBeInTheDocument();
    expect(within(secondRow as HTMLElement).getByRole('button', { name: 'Disable' })).toBeInTheDocument();
    expect(within(secondRow as HTMLElement).getByRole('button', { name: 'Remove' })).toBeInTheDocument();
  });

  it('add posts label and api_key and shows the returned message', async () => {
    apiMocks.torboxAccounts.mockResolvedValue({ accounts });
    apiMocks.torboxAccountAdd.mockResolvedValue({ ok: true, id: 3, message: 'account third added' });
    renderWithClient(<TorboxAccounts {...noop} />);
    await screen.findByText('main');
    await userEvent.type(screen.getByLabelText('New account label'), 'third');
    await userEvent.type(screen.getByLabelText('New account API key'), 'k3');
    await userEvent.click(screen.getByRole('button', { name: 'Add account' }));
    expect(apiMocks.torboxAccountAdd).toHaveBeenCalledWith({ label: 'third', api_key: 'k3' });
    expect(await screen.findByText('account third added')).toBeInTheDocument();
  });

  it('remove shows a refusal message and keeps the row', async () => {
    apiMocks.torboxAccounts.mockResolvedValue({ accounts });
    apiMocks.torboxAccountDelete.mockResolvedValue({ ok: false, message: '1 title still on this account; disable it instead, they move on their next play' });
    renderWithClient(<TorboxAccounts {...noop} />);
    await screen.findByText('second');
    const rows = screen.getAllByRole('listitem');
    const secondRow = rows.find((r) => r.textContent?.includes('second')) as HTMLElement;
    await userEvent.click(within(secondRow).getByRole('button', { name: 'Remove' }));
    expect(apiMocks.torboxAccountDelete).toHaveBeenCalledWith(2);
    expect(await screen.findByText(/still on this account/)).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
  });
});

describe('FilterRulesLink', () => {
  it('navigates react-router to the Filter rules tab hash on click', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/admin']}>
          <FilterRulesLink {...noop} />
          <HashProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('');
    await userEvent.click(screen.getByRole('link', { name: 'Open the Filter rules tab' }));
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('#filter-rules');
  });
});
