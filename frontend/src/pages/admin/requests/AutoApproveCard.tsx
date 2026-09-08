import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api';
import type { GenreRule } from '../../../api';
import { Card, GenreRuleRows } from '../../../components/primitives';

export function AutoApproveCard() {
  const qc = useQueryClient();
  const [msg, setMsg] = useState('');
  const { data } = useQuery({ queryKey: ['auto-approve-rules'], queryFn: api.autoApproveGenreRules });
  const { data: movieGenres } = useQuery({ queryKey: ['genres', 'movie'], queryFn: () => api.genres('movie') });
  const { data: tvGenres } = useQuery({ queryKey: ['genres', 'tv'], queryFn: () => api.genres('tv') });

  const [rules, setRules] = useState<GenreRule[] | null>(null);
  const effectiveRules = rules ?? data?.rules ?? [];

  const saveMutation = useMutation({
    mutationFn: (r: GenreRule[]) => api.setAutoApproveGenreRules(r),
    onSuccess: () => { setMsg('Saved.'); qc.invalidateQueries({ queryKey: ['auto-approve-rules'] }); },
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });
  const runMutation = useMutation({
    mutationFn: api.runAutoApproveNow,
    onSuccess: () => setMsg('Started in the background - check logs for progress.'),
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });

  const addRule = () => {
    const genres = movieGenres?.genres || [];
    const first = genres[0];
    setRules([
      ...effectiveRules,
      {
        media_type: 'movie', genre_id: first?.id || 0, genre_name: first?.name || '',
        year_from: null, year_to: null, enabled: true,
      },
    ]);
  };

  const updateRule = (i: number, patch: Partial<GenreRule>) => {
    const next = effectiveRules.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
    setRules(next);
  };

  const removeRule = (i: number) => {
    setRules(effectiveRules.filter((_, idx) => idx !== i));
  };

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">Auto-approve</h3>
      <p className="mt-0.5 text-xs text-muted">Rules that request titles on their own, up to the daily caps in Settings.</p>
      <Card className="space-y-4">
        <p className="text-sm text-muted">
          Automatically request titles matching enabled genre rules (year-ranged) and any
          user&apos;s followed actors, up to the daily caps in Settings &gt; Auto-approve.
        </p>

        <GenreRuleRows
          rules={effectiveRules}
          movieGenres={movieGenres?.genres || []}
          tvGenres={tvGenres?.genres || []}
          onUpdate={updateRule}
          onRemove={removeRule}
        />

        <div className="flex flex-wrap gap-2">
          <button onClick={addRule} className="rounded border border-border px-3 py-1.5 text-sm hover:bg-bg">
            + Add genre rule
          </button>
          <button
            onClick={() => saveMutation.mutate(effectiveRules)}
            disabled={saveMutation.isPending}
            className="rounded bg-accent px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save rules'}
          </button>
          <button
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
            className="rounded border border-border px-3 py-1.5 text-sm hover:bg-bg disabled:opacity-50"
          >
            Run now
          </button>
        </div>

        {msg && <div className="font-mono text-xs text-muted">{msg}</div>}
      </Card>
    </section>
  );
}
