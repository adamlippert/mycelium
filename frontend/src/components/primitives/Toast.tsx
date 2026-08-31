import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export type ToastKind = 'ok' | 'err';

export interface ToastItem {
  id: number;
  title: string;
  message?: string;
  kind: ToastKind;
}

export type ToastFn = (title: string, message?: string, kind?: ToastKind) => void;

interface ToastContextValue {
  toast: ToastFn;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// Mirrors the old Jinja dashboard's toast() (templates/ui.html, ~line 992):
// same 5s auto-dismiss, same ok/err accent-edge distinction.
export const TOAST_DISMISS_MS = 5000;

const ACCENT: Record<ToastKind, string> = { ok: '#7bd0a7', err: '#e48181' };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const toast = useCallback<ToastFn>((title, message, kind = 'ok') => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { id, title, message, kind }]);
    timers.current.set(id, setTimeout(() => dismiss(id), TOAST_DISMISS_MS));
  }, [dismiss]);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toasts.length > 0 && (
        <div
          aria-live="polite"
          className="pointer-events-none fixed bottom-4 right-4 z-[300] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
        >
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex items-start gap-3 rounded-xl border border-border
                         bg-card p-3 shadow-2xl"
              style={{ borderLeft: `4px solid ${ACCENT[t.kind]}` }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-body">{t.title}</div>
                {t.message && <div className="mt-0.5 text-xs text-muted">{t.message}</div>}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="flex-none rounded p-0.5 text-muted hover:text-white"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}

/** Throws outside a ToastProvider - every consumer is expected to mount
 * under the single provider in App.tsx, so a missing provider is a bug,
 * not a state to render around. */
export function useToast(): ToastFn {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx.toast;
}
