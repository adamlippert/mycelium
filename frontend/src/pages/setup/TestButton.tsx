import { useState } from 'react';
import { csrfToken } from '../../api';

type ResultStatus = 'idle' | 'pending' | 'ok' | 'err';

interface Result {
  status: ResultStatus;
  text: string;
}

const RESULT_CLASS: Record<ResultStatus, string> = {
  idle: '',
  pending: 'text-warn',
  ok: 'text-ok',
  err: 'text-danger',
};

/** Mirrors setup.html's testConn(kind): posts the full current wizard state
 * (via buildFormData) to /setup/test/<kind>, renders {ok, detail|error}. */
export default function TestButton({
  kind,
  label,
  buildFormData,
}: {
  kind: string;
  label: string;
  buildFormData: () => FormData;
}) {
  const [result, setResult] = useState<Result>({ status: 'idle', text: '' });

  async function run() {
    setResult({ status: 'pending', text: '...' });
    try {
      const r = await fetch(`/setup/test/${kind}`, {
        method: 'POST',
        body: buildFormData(),
        headers: { 'X-CSRFToken': csrfToken() },
      });
      const d = await r.json();
      setResult(
        d.ok
          ? { status: 'ok', text: `✓ ${d.detail || 'connected'}` }
          : { status: 'err', text: `✗ ${d.error || 'failed'}` },
      );
    } catch (e: any) {
      setResult({ status: 'err', text: `✗ ${e.message}` });
    }
  }

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <button
        type="button"
        onClick={run}
        className="rounded border border-border bg-card-raised px-3 py-1.5 text-[11px] font-semibold
                   text-accent-light hover:bg-white/[0.06]"
      >
        {label}
      </button>
      {result.status !== 'idle' && (
        <span className={`text-xs ${RESULT_CLASS[result.status]}`}>{result.text}</span>
      )}
    </div>
  );
}
