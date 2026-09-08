import type { ComponentType } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { ServiceTest } from './ServiceTest';
import { SettingField } from './SettingField';
import { isVisible, matchesQuery } from './visibility';
import type { FieldValue, Values } from './visibility';

export type Endpoint = 'settings' | 'setup';

export const SERVICE_LABEL: Record<string, string> = {
  torbox: 'TorBox', realdebrid: 'RealDebrid', tmdb: 'TMDB', zilean: 'Zilean', zilean_pg: 'Postgres',
  debridio: 'Debridio', jellyfin: 'Jellyfin', seerr: 'Seerr', radarr: 'Radarr', sonarr: 'Sonarr',
  trakt: 'Trakt', opensubtitles: 'OpenSubtitles', discord: 'Discord', telegram: 'Telegram', oidc: 'OIDC',
  comet: 'Comet', mediafusion: 'MediaFusion',
};

export type CustomCard = ComponentType<{ values: Values; onChange: (key: string, next: FieldValue) => void }>;

/** The fields of one section or wizard step: dependent fields hidden until
 * their toggle is on, advanced fields hidden in Simple mode, one Test button
 * per service after the last of its fields, custom cards by name. */
export function FieldList({
  fields, sections, values, onChange, advanced, query = '', custom = {}, endpoint = 'settings',
}: {
  fields: SettingsField[];
  sections: SettingsSection[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
  advanced: boolean;
  query?: string;
  custom?: Record<string, CustomCard>;
  endpoint?: Endpoint;
}) {
  const visible = fields.filter((f) => f.kind === 'custom' || isVisible(f, values, advanced));
  const lastOfService: Record<string, string> = {};
  visible.forEach((f) => { if (f.test) lastOfService[f.test] = f.key; });
  return (
    <>
      {visible.map((f) => {
        if (f.kind === 'custom') {
          const C = custom[f.component || ''];
          return C ? <div key={f.key} className="py-3"><C values={values} onChange={onChange} /></div> : null;
        }
        return (
          <div key={f.key}>
            <SettingField field={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} values={values} sections={sections}
              dimmed={!matchesQuery(f, query)} endpoint={endpoint} />
            {f.test && lastOfService[f.test] === f.key && (
              <ServiceTest service={f.test} label={SERVICE_LABEL[f.test] || f.test} sections={sections} values={values} endpoint={endpoint} />
            )}
          </div>
        );
      })}
    </>
  );
}
