import { NavLink } from 'react-router-dom';
import { Icon, type IconName } from '../../design/icons';

export function NavItem({
  to,
  label,
  icon,
  exact,
  count,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: IconName;
  exact?: boolean;
  count?: number;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={exact}
      onClick={onNavigate}
      className={({ isActive }) =>
        `mx-2 flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] font-medium transition-all ${
          isActive ? 'text-white' : 'text-muted hover:text-body'
        }`
      }
      style={({ isActive }) =>
        isActive
          ? { background: 'var(--nav-active)', boxShadow: 'inset 2px 0 0 #9f92ff' }
          : undefined
      }
    >
      <Icon name={icon} className="h-[18px] w-[18px] flex-none" />
      <span>{label}</span>
      {count !== undefined && (
        <span className="ml-auto rounded px-1.5 py-0.5 font-mono text-[10px] text-muted"
              style={{ background: 'var(--surface-subtle)' }}>
          {count}
        </span>
      )}
    </NavLink>
  );
}
