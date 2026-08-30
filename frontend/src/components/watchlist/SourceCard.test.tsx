import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { SourceCard } from './SourceCard';

describe('SourceCard', () => {
  it('shows the source identity and detail line', () => {
    render(<SourceCard abbr="TR" name="Trakt" detail="adamlippert" connected onSync={() => {}} />);
    expect(screen.getByText('TR')).toBeInTheDocument();
    expect(screen.getByText('Trakt')).toBeInTheDocument();
    expect(screen.getByText('adamlippert')).toBeInTheDocument();
  });

  it('marks connection state as a pill', () => {
    render(<SourceCard abbr="MD" name="MDBList" detail="" connected={false} />);
    expect(screen.getByText('Not connected')).toBeInTheDocument();
  });

  it('fires onSync and disables while syncing', async () => {
    const onSync = vi.fn();
    const { rerender } = render(<SourceCard abbr="TR" name="Trakt" detail="" connected onSync={onSync} />);
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(onSync).toHaveBeenCalledOnce();

    rerender(<SourceCard abbr="TR" name="Trakt" detail="" connected onSync={onSync} syncing />);
    expect(screen.getByRole('button', { name: 'Syncing...' })).toBeDisabled();
  });

  it('hides the sync action when there is no handler', () => {
    render(<SourceCard abbr="MD" name="MDBList" detail="" connected />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
