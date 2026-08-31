import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Card, Pill } from '../../components/primitives';

export default function Releases() {
  const releasesQ = useQuery({ queryKey: ['admin-releases'], queryFn: api.releases });
  const releases = releasesQ.data?.releases ?? [];

  return (
    <Card>
      <div className="mb-3 text-sm font-semibold text-body">Releases</div>
      {releasesQ.isLoading ? (
        <p className="text-xs text-muted">Loading…</p>
      ) : releases.length === 0 ? (
        <p className="text-xs text-muted">No releases yet</p>
      ) : (
        <div className="space-y-3">
          {releases.map((rel, i) => (
            <div key={rel.version} className="text-xs">
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold text-body">v{rel.version}</span>
                <span className="text-muted">{rel.date}</span>
                {i === 0 && <Pill state="ready">current</Pill>}
              </div>
              {rel.notes.length > 0 && (
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted">
                  {rel.notes.map((note, j) => (
                    <li key={j}>{note}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
