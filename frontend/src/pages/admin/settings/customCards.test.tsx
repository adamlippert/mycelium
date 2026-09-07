import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FilterRulesLink, LegacyPassword, WebhookSecret } from './customCards';

const apiMocks = vi.hoisted(() => ({
  setLegacyPassword: vi.fn(), webhookSecret: vi.fn(),
}));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderWithClient(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{children}</QueryClientProvider>);
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
});

describe('FilterRulesLink', () => {
  it('links to the Filter rules tab', () => {
    renderWithClient(<FilterRulesLink {...noop} />);
    expect(screen.getByRole('link', { name: 'Open the Filter rules tab' })).toHaveAttribute('href', '#filter-rules');
  });
});
