import type { SettingsSection } from '../../../api';
import { Card } from '../../../components/primitives';
import { FieldList } from './FieldList';
import type { CustomCard } from './FieldList';
import { dependsSatisfied, isVisible } from './visibility';
import type { FieldValue, Values } from './visibility';

export function SectionView({
  section, sections, values, onChange, advanced, query, custom,
}: {
  section: SettingsSection;
  sections: SettingsSection[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
  advanced: boolean;
  query: string;
  custom: Record<string, CustomCard>;
}) {
  const visible = section.fields.filter((f) => f.kind === 'custom' || isVisible(f, values, advanced));
  // Only claim "switch to Advanced to see it" when a field is hidden purely
  // by the Simple/Advanced mode: a field also gated by a failed depends_on
  // would stay hidden even after switching, so it must not count.
  const allAdvancedHidden = visible.every((f) => f.kind === 'custom')
    && section.fields.some((f) => f.advanced && dependsSatisfied(f, values));
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
        <FieldList fields={section.fields} sections={sections} values={values} onChange={onChange} advanced={advanced} query={query} custom={custom} />
      </Card>
    </div>
  );
}
