import type { ComponentType } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { Card } from '../../../components/primitives';
import { ServiceTest } from './ServiceTest';
import { SettingField } from './SettingField';
import { dependsSatisfied, isVisible, matchesQuery } from './visibility';
import type { FieldValue, Values } from './visibility';

const SERVICE_LABEL: Record<string, string> = {
  torbox: 'TorBox', realdebrid: 'RealDebrid', tmdb: 'TMDB', zilean: 'Zilean', zilean_pg: 'Postgres',
  debridio: 'Debridio', jellyfin: 'Jellyfin', seerr: 'Seerr', radarr: 'Radarr', sonarr: 'Sonarr',
  trakt: 'Trakt', opensubtitles: 'OpenSubtitles', discord: 'Discord', telegram: 'Telegram', oidc: 'OIDC',
};

export function SectionView({
  section, sections, values, onChange, advanced, query, custom,
}: {
  section: SettingsSection;
  sections: SettingsSection[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
  advanced: boolean;
  query: string;
  custom: Record<string, ComponentType<{ values: Values; onChange: (key: string, next: FieldValue) => void }>>;
}) {
  const visible = section.fields.filter((f) => f.kind === 'custom' || isVisible(f, values, advanced));
  // Only claim "switch to Advanced to see it" when a field is hidden purely
  // by the Simple/Advanced mode: a field also gated by a failed depends_on
  // would stay hidden even after switching, so it must not count.
  const allAdvancedHidden = visible.every((f) => f.kind === 'custom')
    && section.fields.some((f) => f.advanced && dependsSatisfied(f, values));
  // A service's Test button sits after the last of its fields.
  const lastOfService: Record<string, string> = {};
  visible.forEach((f) => { if (f.test) lastOfService[f.test] = f.key; });
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold">{section.title}</h2>
        <p className="text-sm text-muted">{section.description}</p>
      </div>
      {allAdvancedHidden && (
        <p className="text-sm text-muted">Everything here is an advanced setting. Switch to Advanced above to see it.</p>
      )}
      <Card>
        {visible.map((f: SettingsField) => {
          if (f.kind === 'custom') {
            const C = custom[f.component || ''];
            return C ? <div key={f.key} className="py-3"><C values={values} onChange={onChange} /></div> : null;
          }
          return (
            <div key={f.key}>
              <SettingField field={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} values={values} sections={sections} dimmed={!matchesQuery(f, query)} />
              {f.test && lastOfService[f.test] === f.key && (
                <ServiceTest service={f.test} label={SERVICE_LABEL[f.test] || f.test} sections={sections} values={values} />
              )}
            </div>
          );
        })}
      </Card>
    </div>
  );
}
