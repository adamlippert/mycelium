export type AddStatus = 'idle' | 'adding' | 'added' | 'pending' | 'error' | 'wanted' | 'upcoming';

export function LibraryButton({
  libStatus,
  addStatus,
  mediaType,
  disabled,
  onAdd,
}: {
  libStatus: string | undefined;
  addStatus: string;
  mediaType: string;
  disabled: boolean;
  onAdd: () => void;
}) {
  if (libStatus === 'available' || libStatus === 'success') {
    return (
      <button type="button" disabled className="px-4 py-2 rounded-lg bg-ok/20 text-ok font-medium text-sm cursor-default">
        In library
      </button>
    );
  }
  if (libStatus === 'wanted' || libStatus === 'upcoming' || libStatus === 'pending' || libStatus === 'failed') {
    return (
      <button type="button" disabled className="px-4 py-2 rounded-lg bg-warn/20 text-warn font-medium text-sm cursor-default">
        Wanted
      </button>
    );
  }
  if (addStatus === 'wanted' || addStatus === 'upcoming') {
    return (
      <button type="button" disabled className="px-4 py-2 rounded-lg bg-warn/20 text-warn font-medium text-sm cursor-default">
        {addStatus === 'upcoming' ? 'Upcoming' : 'Wanted'}
      </button>
    );
  }
  const isbusy = addStatus === 'adding' || addStatus === 'added' || addStatus === 'pending';
  return (
    <button
      type="button"
      onClick={onAdd}
      disabled={isbusy || disabled}
      className="bg-accent hover:bg-accent-light text-white rounded-lg px-4 py-2 text-sm font-medium
                 disabled:opacity-60 disabled:cursor-not-allowed"
    >
      {addStatus === 'adding'
        ? 'Processing...'
        : addStatus === 'added'
        ? 'Added'
        : addStatus === 'pending'
        ? 'Pending approval'
        : addStatus === 'error'
        ? 'Retry'
        : mediaType === 'tv'
        ? '+ Monitor series'
        : '+ Add to library'}
    </button>
  );
}
