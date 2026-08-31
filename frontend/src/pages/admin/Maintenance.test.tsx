import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Maintenance from './Maintenance';

const apiMocks = vi.hoisted(() => ({
  repairOverview: vi.fn(),
  maintenanceRepairAll: vi.fn(),
  maintenanceRunCleanup: vi.fn(),
  maintenanceAutoUpgrade: vi.fn(),
  maintenancePackConsolidate: vi.fn(),
  maintenanceMergeSeries: vi.fn(),
  maintenanceSyncSeerr: vi.fn(),
  maintenanceLibraryImport: vi.fn(),
  maintenanceFixCovers: vi.fn(),
  maintenanceGenerateNfos: vi.fn(),
  maintenanceDbVacuum: vi.fn(),
  maintenanceRecovery: vi.fn(),
  maintenanceStrmRescan: vi.fn(),
  fixImdbTitles: vi.fn(),
  repairTvshowTitles: vi.fn(),
  clearRetryQueue: vi.fn(),
  maintenanceAddMagnet: vi.fn(),
  maintenanceTorboxDelete: vi.fn(),
  maintenanceBackupRestore: vi.fn(),
  maintenanceShowOverrideDelete: vi.fn(),
  arrStatus: vi.fn(),
  arrTest: vi.fn(),
  arrRun: vi.fn(),
  seriesBackfill: vi.fn(),
  migrateCanonical: vi.fn(),
  cleanupDuplicateStrms: vi.fn(),
  repairStrms: vi.fn(),
  scanTorboxLibrary: vi.fn(),
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
  return render(<QueryClientProvider client={qc}><Maintenance /></QueryClientProvider>);
}

describe('Maintenance tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.repairOverview.mockResolvedValue({
      items: [
        {
          path: '/data/media/movies/Foo (2024)/Foo (2024).strm',
          title: 'Foo',
          media_type: 'movie',
          status: 'ok',
          old_torrent_id: null,
          new_info_hash: null,
          reason: null,
          created_at: '2026-08-20 10:00:00',
        },
      ],
      last_cleanup: { scanned: 120, repaired: 5, deleted: 2, unfixable: 1, ran_at: '2026-08-20 10:00:00' },
    });
    apiMocks.arrStatus.mockResolvedValue({
      running: false, kind: null, total: 0, done: 0, added: 0, skipped: 0, errors: 0, message: '',
    });
    for (const fn of Object.values(apiMocks)) {
      if (fn !== apiMocks.repairOverview && fn !== apiMocks.arrStatus) fn.mockResolvedValue({});
    }
  });

  it('renders the four maintenance groups with a named action per group', async () => {
    renderIt();
    expect(screen.getByText('Library')).toBeInTheDocument();
    expect(screen.getByText('Import & Sync')).toBeInTheDocument();
    expect(screen.getByText('Jellyfin')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run cleanup' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Repair strm files' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vacuum DB' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recovery wizard' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Force strm rescan' })).toBeInTheDocument();
  });

  it('renders the repair summary from the mocked /ui/api/repair payload', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('120')).toBeInTheDocument();
      expect(screen.getByText('5')).toBeInTheDocument();
      expect(screen.getByText('Foo')).toBeInTheDocument();
    });
  });

  it('does not run the mutation when a confirm-guarded action is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderIt();
    await userEvent.click(screen.getByRole('button', { name: 'Vacuum DB' }));
    expect(apiMocks.maintenanceDbVacuum).not.toHaveBeenCalled();
  });

  it('runs the mutation for a confirm-guarded action when confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderIt();
    await userEvent.click(screen.getByRole('button', { name: 'Recovery wizard' }));
    await waitFor(() => expect(apiMocks.maintenanceRecovery).toHaveBeenCalled());
  });

  it('runs a non-guarded action without confirming', async () => {
    renderIt();
    await userEvent.click(screen.getByRole('button', { name: 'Run cleanup' }));
    await waitFor(() => expect(apiMocks.maintenanceRunCleanup).toHaveBeenCalled());
  });

  it('runs the strm rescan action without confirming', async () => {
    renderIt();
    await userEvent.click(screen.getByRole('button', { name: 'Force strm rescan' }));
    await waitFor(() => expect(apiMocks.maintenanceStrmRescan).toHaveBeenCalled());
  });
});
