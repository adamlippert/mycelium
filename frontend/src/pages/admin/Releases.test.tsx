import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Releases from './Releases';

const releasesMock = vi.fn();

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      releases: () => releasesMock(),
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Releases /></QueryClientProvider>);
}

describe('Releases tab', () => {
  it('lists a version and one of its notes', async () => {
    releasesMock.mockResolvedValue({
      releases: [
        { version: '0.7.7', date: '2026-08-20', notes: ['Fixed streaming bug'] },
        { version: '0.7.6', date: '2026-08-10', notes: ['Earlier release'] },
      ],
    });
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('v0.7.7')).toBeInTheDocument();
      expect(screen.getByText('Fixed streaming bug')).toBeInTheDocument();
    });
  });

  it('shows "No releases yet" when there are none', async () => {
    releasesMock.mockResolvedValue({ releases: [] });
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('No releases yet')).toBeInTheDocument();
    });
  });
});
