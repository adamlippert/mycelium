import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import type { SettingItem } from '../../api';
import { Card } from '../../components/primitives/Card';
import { Toggle } from '../../components/primitives/Toggle';
import { Chip } from '../../components/primitives/Chip';
import {
  STATE_NAMES,
  STATE_LABELS,
  buildState,
  assign,
  reorder,
  availableFor,
  invalidValues,
  toFormFields,
  displayValue,
  visibleChips,
} from './filterRulesModel';
import type { FilterRuleState, RawCurrent, StateName } from './filterRulesModel';

// Mirrors initFilterRules' fold in static/admin/filter_rules.js: all_for_ui
// sends 35 flat keys (7 categories x 4 states + 7 strict toggles), grouped
// here into one FilterRuleState per category.
const CATEGORY_KEY_RE = /^(.*)_(PREFERRED|EXCLUDED|REQUIRED|INCLUDED|STRICT)$/;

function groupItems(items: SettingItem[]): Record<string, FilterRuleState> {
  const byPrefix: Record<string, { current: RawCurrent; options: string[]; strict: boolean }> = {};
  items.forEach((item) => {
    const m = item.key.match(CATEGORY_KEY_RE);
    if (!m) return;
    const [, prefix, suffix] = m;
    if (!byPrefix[prefix]) byPrefix[prefix] = { current: {}, options: [], strict: false };
    if (suffix === 'STRICT') {
      byPrefix[prefix].strict = Boolean(item.value);
    } else {
      const stateName = suffix.toLowerCase() as StateName;
      byPrefix[prefix].current[stateName] = item.value;
      if (item.options && item.options.length) byPrefix[prefix].options = item.options;
    }
  });
  const states: Record<string, FilterRuleState> = {};
  Object.keys(byPrefix).forEach((prefix) => {
    const raw = byPrefix[prefix];
    states[prefix] = buildState(prefix.toLowerCase(), raw.options, raw.current, raw.strict);
  });
  return states;
}

function categoryLabel(category: string): string {
  return category.replace('_', ' ').toUpperCase();
}

function CategoryPanel({
  prefix,
  state,
  expandedRows,
  onExpandRow,
  onChange,
}: {
  prefix: string;
  state: FilterRuleState;
  expandedRows: Record<string, boolean>;
  onExpandRow: (key: string) => void;
  onChange: (next: FilterRuleState) => void;
}) {
  const invalid = new Set(invalidValues(state));

  return (
    <Card>
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <strong className="text-sm">{categoryLabel(state.category)}</strong>
          <span className="text-xs text-muted">{state.options.length} values</span>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          strict
          <Toggle
            checked={state.strict}
            onChange={(next) => onChange({ ...state, strict: next })}
            label={`${categoryLabel(state.category)} strict`}
          />
        </label>
      </div>

      <div className="space-y-3">
        {STATE_NAMES.map((name) => {
          const values = state.states[name];
          const rowKey = `${prefix}_${name}`;
          const expanded = Boolean(expandedRows[rowKey]);
          const { shown, hidden } = visibleChips(values, expanded);
          const options = availableFor(state);

          return (
            <div key={name} data-state={name}>
              <div className="mb-1 flex items-center gap-2">
                <span className="w-20 flex-none text-xs font-medium text-muted">
                  {STATE_LABELS[name]}
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {values.length === 0 && <span className="text-xs text-muted">(none)</span>}
                  {shown.map((value) => (
                    <span key={value} className="inline-flex items-center gap-0.5">
                      {name === 'preferred' && (
                        <button
                          type="button"
                          title={`Move ${value} earlier in the preference order`}
                          aria-label={`Move ${value} earlier`}
                          className="text-xs text-muted hover:text-body"
                          onClick={() => onChange(reorder(state, 'preferred', value, -1))}
                        >
                          &lt;
                        </button>
                      )}
                      <Chip
                        label={
                          (invalid.has(value) ? '! ' : '') + displayValue(state.category, value)
                        }
                        onRemove={() => onChange(assign(state, value, null))}
                      />
                      {name === 'preferred' && (
                        <button
                          type="button"
                          title={`Move ${value} later in the preference order`}
                          aria-label={`Move ${value} later`}
                          className="text-xs text-muted hover:text-body"
                          onClick={() => onChange(reorder(state, 'preferred', value, 1))}
                        >
                          &gt;
                        </button>
                      )}
                    </span>
                  ))}
                  {hidden > 0 && (
                    <button
                      type="button"
                      className="text-xs text-accent hover:underline"
                      onClick={() => onExpandRow(rowKey)}
                    >
                      +{hidden} more
                    </button>
                  )}
                  <select
                    className="rounded border border-border bg-bg px-2 py-1 text-xs"
                    value=""
                    aria-label={`Add a ${STATE_LABELS[name].toLowerCase()} value to ${state.category}`}
                    onChange={(e) => {
                      if (e.target.value) onChange(assign(state, e.target.value, name));
                    }}
                  >
                    <option value="">+ add</option>
                    {options.map((v) => (
                      <option key={v} value={v}>
                        {displayValue(state.category, v)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {name === 'included' && (
                <p className="text-warn text-[11px]">
                  overrides every other rule in every category - use deliberately
                </p>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export default function FilterRules() {
  const { data } = useQuery({ queryKey: ['admin-settings'], queryFn: api.settings });
  const [states, setStates] = useState<Record<string, FilterRuleState> | null>(null);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!data || states) return;
    const group = data.groups.find((g) => g.id === 'filter_rules');
    if (group) setStates(groupItems(group.items));
  }, [data, states]);

  const saveMut = useMutation({
    mutationFn: async () => {
      if (!states) return;
      const fields: Record<string, string> = {};
      Object.keys(states).forEach((prefix) => {
        Object.assign(fields, toFormFields(states[prefix], prefix));
      });
      await api.saveSettings(fields);
    },
    onSuccess: () => setSavedAt(Date.now()),
  });

  if (!states) {
    return <p className="text-muted text-sm">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Filtering rules</h2>
        <div className="flex items-center gap-3">
          {savedAt && !saveMut.isPending && (
            <span className="text-xs text-ok">Saved</span>
          )}
          <button
            type="button"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="rounded bg-accent px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
          >
            {saveMut.isPending ? 'Saving...' : 'Save all'}
          </button>
        </div>
      </div>
      {saveMut.isError && (
        <p className="text-xs text-danger">
          {(saveMut.error as Error)?.message || 'Save failed'}
        </p>
      )}

      {Object.keys(states).map((prefix) => (
        <CategoryPanel
          key={prefix}
          prefix={prefix}
          state={states[prefix]}
          expandedRows={expandedRows}
          onExpandRow={(key) => setExpandedRows((prev) => ({ ...prev, [key]: true }))}
          onChange={(next) => setStates((prev) => ({ ...(prev as Record<string, FilterRuleState>), [prefix]: next }))}
        />
      ))}
    </div>
  );
}
