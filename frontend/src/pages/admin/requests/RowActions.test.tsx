import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RowActions } from './RowActions';
import { row } from './fixtures';

const apiMocks = vi.hoisted(() => ({ approveRequest: vi.fn(), denyRequest: vi.fn(), reopenRequest: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

describe('RowActions', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pending: approve posts and reports; deny is inline with a note and can be cancelled', async () => {
    apiMocks.approveRequest.mockResolvedValue({ ok: true });
    apiMocks.denyRequest.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<RowActions row={row({})} overQuota={false} onDone={onDone} />);
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    expect(screen.getByRole('textbox', { name: 'Reason' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Reason' }), 'too big');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.denyRequest).toHaveBeenCalledWith(1, 'too big'));
    expect(onDone).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(apiMocks.approveRequest).toHaveBeenCalledWith(1));
    expect(await screen.findByText('approved')).toBeInTheDocument();
  });

  it('denied: reopen and approve; approved: nothing; over quota shows the hint', async () => {
    apiMocks.reopenRequest.mockResolvedValue({ ok: true, message: 'back in the pending list' });
    const { rerender } = render(<RowActions row={row({ status: 'denied' })} overQuota onDone={() => {}} />);
    expect(screen.getByText('over quota')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    await waitFor(() => expect(apiMocks.reopenRequest).toHaveBeenCalledWith(1));
    expect(await screen.findByText('back in the pending list')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    rerender(<RowActions row={row({ status: 'approved' })} overQuota={false} onDone={() => {}} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
