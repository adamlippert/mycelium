import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { QuotaCard } from './QuotaCard';

const quota = vi.fn();
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, myQuota: () => quota() } };
});

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><QuotaCard /></QueryClientProvider>);
}

describe('QuotaCard', () => {
  it('shows used of limit with the reset date', async () => {
    quota.mockResolvedValue({ used: 14, limit: 25, resets_at: '2026-10-01T00:00:00Z', unlimited: false });
    renderCard();
    await waitFor(() => expect(screen.getByText('14')).toBeInTheDocument());
    expect(screen.getByText(/of 25 requests/)).toBeInTheDocument();
    expect(screen.getByText(/Resets/)).toBeInTheDocument();
  });

  it('renders nothing for an unlimited user', async () => {
    quota.mockResolvedValue({ used: 3, limit: 0, resets_at: '2026-10-01T00:00:00Z', unlimited: true });
    const { container } = renderCard();
    await waitFor(() => expect(quota).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('turns the bar warning-coloured at 80 percent', async () => {
    quota.mockResolvedValue({ used: 20, limit: 25, resets_at: '2026-10-01T00:00:00Z', unlimited: false });
    const { container } = renderCard();
    await waitFor(() => expect(screen.getByText('20')).toBeInTheDocument());
    const bar = container.querySelector('[data-quota-bar]') as HTMLElement;
    expect(bar.style.width).toBe('80%');
    expect(bar.style.background).toContain('--dot-warn');
  });
});
