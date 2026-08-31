import { useState } from 'react';
import { useQueryClient, useMutation } from '@tanstack/react-query';
import { api } from '../../api';
import { useToast } from '../primitives';
import type { SessionInfo } from '../../types';

const REGIONS: { code: string; flag: string; name: string }[] = [
  { code: 'NL', flag: '\u{1F1F3}\u{1F1F1}', name: 'Netherlands' },
  { code: 'BE', flag: '\u{1F1E7}\u{1F1EA}', name: 'Belgium' },
  { code: 'ZA', flag: '\u{1F1FF}\u{1F1E6}', name: 'South Africa' },
  { code: 'US', flag: '\u{1F1FA}\u{1F1F8}', name: 'United States' },
  { code: 'GB', flag: '\u{1F1EC}\u{1F1E7}', name: 'United Kingdom' },
  { code: 'DE', flag: '\u{1F1E9}\u{1F1EA}', name: 'Germany' },
  { code: 'FR', flag: '\u{1F1EB}\u{1F1F7}', name: 'France' },
  { code: 'ES', flag: '\u{1F1EA}\u{1F1F8}', name: 'Spain' },
  { code: 'IT', flag: '\u{1F1EE}\u{1F1F9}', name: 'Italy' },
  { code: 'AU', flag: '\u{1F1E6}\u{1F1FA}', name: 'Australia' },
  { code: 'CA', flag: '\u{1F1E8}\u{1F1E6}', name: 'Canada' },
  { code: 'BR', flag: '\u{1F1E7}\u{1F1F7}', name: 'Brazil' },
  { code: 'IN', flag: '\u{1F1EE}\u{1F1F3}', name: 'India' },
  { code: 'JP', flag: '\u{1F1EF}\u{1F1F5}', name: 'Japan' },
  { code: 'KR', flag: '\u{1F1F0}\u{1F1F7}', name: 'South Korea' },
  { code: 'SE', flag: '\u{1F1F8}\u{1F1EA}', name: 'Sweden' },
  { code: 'NO', flag: '\u{1F1F3}\u{1F1F4}', name: 'Norway' },
  { code: 'DK', flag: '\u{1F1E9}\u{1F1F0}', name: 'Denmark' },
  { code: 'PT', flag: '\u{1F1F5}\u{1F1F9}', name: 'Portugal' },
  { code: 'PL', flag: '\u{1F1F5}\u{1F1F1}', name: 'Poland' },
];

export function RegionPicker({ region }: { region: string }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  const mutation = useMutation({
    mutationFn: (code: string) => api.setRegion(code),
    onSuccess: (r) => {
      // Patch the cached session directly instead of invalidating it. A
      // refetch of GET /ui/api/session re-derives region from
      // auth.current_user_record() (app.py:2954/2963), which for the legacy
      // single-user login is a synthetic dict with no region to read back
      // (auth.py:170) - POST /ui/api/me/region can't persist anything for
      // that account either (app.py's ui_api_me_region now 409s for it), so
      // a refetch would just re-show the old region. Patching the cache
      // keeps the picker correct for that setup, and is harmless for real
      // multi-user accounts where the write actually landed server-side.
      queryClient.setQueryData<SessionInfo>(['session'], (old) =>
        old?.user ? { ...old, user: { ...old.user, region: r.region } } : old,
      );
      queryClient.invalidateQueries({ queryKey: ['trending'] });
      queryClient.invalidateQueries({ queryKey: ['popular'] });
      queryClient.invalidateQueries({ queryKey: ['top-rated'] });
      queryClient.invalidateQueries({ queryKey: ['now-playing'] });
      queryClient.invalidateQueries({ queryKey: ['upcoming'] });
      queryClient.invalidateQueries({ queryKey: ['providers'] });
      queryClient.invalidateQueries({ queryKey: ['by-provider'] });
    },
    onError: (err: Error) => toast('Could not save region', err.message, 'err'),
  });

  const current = REGIONS.find((r) => r.code === region);
  const flag = current?.flag || region;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-sm
                   transition hover:border-accent-light/50"
        title={current?.name || region}
      >
        <span className="text-base">{flag}</span>
        <span className="text-xs text-muted">{region}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-lg shadow-xl overflow-hidden w-48 max-h-64 overflow-y-auto">
            {REGIONS.map((r) => (
              <button
                key={r.code}
                type="button"
                onClick={() => {
                  mutation.mutate(r.code);
                  setOpen(false);
                }}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition
                  ${r.code === region ? 'bg-accent/10 text-white' : 'text-muted hover:text-white hover:bg-bg'}`}
              >
                <span>{r.flag}</span>
                <span>{r.name}</span>
                <span className="ml-auto text-[10px] opacity-50">{r.code}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
