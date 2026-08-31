import type { PillState } from './Pill';

/**
 * Shared status -> label mapping for request/library statuses ('success',
 * 'wanted', 'upcoming', 'failed', 'pending', ...), used anywhere a status
 * is rendered as a Pill (Requests table, Library table, Search results).
 */
const STATUS_LABELS: Record<string, string> = {
  success: 'In library',
  available: 'In library',
  wanted: 'Wanted',
  upcoming: 'Upcoming',
  failed: 'Failed',
  denied: 'Denied',
  approved: 'Approved',
  pending: 'Processing',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusToPillState(status: string): PillState {
  if (status === 'success' || status === 'available' || status === 'approved') return 'ready';
  if (status === 'pending' || status === 'wanted') return 'queued';
  if (status === 'denied' || status === 'failed') return 'failed';
  return 'lazy';
}
