import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { UserRecord } from '../../types';
import { usePlugins } from '../../hooks/usePlugins';
import { Card, Pill, Toggle, DataTable } from '../../components/primitives';
import type { Column } from '../../components/primitives';

/** First two letters of the username, uppercased, for the avatar badge. */
function initials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

export default function Users() {
  const qc = useQueryClient();
  const { data: users } = useQuery({ queryKey: ['users'], queryFn: api.users });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const { plugins } = usePlugins();

  // Every user-table column a plugin contributes: user_fields + admin_fields,
  // matching plugin_loader.user_fields() / the Jinja togglePluginField() reach.
  const pluginFields = plugins.flatMap((p) =>
    [...(p.user_fields || []), ...(p.admin_fields || [])].map((field) => ({
      field,
      label: p.user_field_labels?.[field] ?? field,
    })),
  );

  const updateMut = useMutation({
    mutationFn: ({ id, fields }: { id: number; fields: Partial<UserRecord> }) =>
      api.updateUser(id, fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });

  const rows = users?.users ?? [];

  const columns: Column<UserRecord>[] = [
    {
      key: 'user',
      header: 'User',
      render: (u) => (
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={`flex h-6 w-6 flex-none items-center justify-center rounded-md text-[10px] font-semibold ${
              u.role === 'admin'
                ? 'border border-accent/30 bg-accent/20 text-accent'
                : 'border border-border bg-white/5 text-muted'
            }`}
          >
            {initials(u.username)}
          </span>
          <span className="truncate font-medium">{u.username}</span>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      render: (u) => <Pill state={u.role === 'admin' ? 'materializing' : 'lazy'}>{u.role}</Pill>,
    },
    {
      key: 'quota',
      header: 'Quota used',
      render: (u) => (
        <span className="font-mono text-xs text-muted">
          {u.quota_monthly === 0 ? 'unlimited' : u.quota_monthly}
        </span>
      ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (u) => (
        <Toggle
          checked={u.enabled}
          onChange={(next) => updateMut.mutate({ id: u.id, fields: { enabled: next } })}
          label={`Enabled for ${u.username}`}
        />
      ),
    },
    {
      key: 'auto_approve',
      header: 'Auto-approve',
      render: (u) => (
        <Toggle
          checked={u.auto_approve}
          onChange={(next) => updateMut.mutate({ id: u.id, fields: { auto_approve: next } })}
          label={`Auto-approve for ${u.username}`}
        />
      ),
    },
    ...pluginFields.map((pf): Column<UserRecord> => ({
      key: `plugin-${pf.field}`,
      header: pf.label,
      render: (u) => (
        <Toggle
          checked={!!(u as unknown as Record<string, unknown>)[pf.field]}
          onChange={(next) => updateMut.mutate({ id: u.id, fields: { [pf.field]: next } as Partial<UserRecord> })}
          label={`${pf.label} for ${u.username}`}
        />
      ),
    })),
    {
      key: 'last_login',
      header: 'Last seen',
      render: (u) => <span className="text-xs text-muted">{u.last_login || '-'}</span>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (u) =>
        session?.user?.id !== u.id ? (
          <button
            type="button"
            onClick={() => confirm(`Delete ${u.username}?`) && deleteMut.mutate(u.id)}
            className="rounded bg-danger/20 px-3 py-1 text-xs text-danger hover:bg-danger/30"
          >
            Delete
          </button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <h2 className="mb-3 text-sm font-semibold">Create user</h2>
        <CreateUserForm />
      </Card>
      <DataTable columns={columns} rows={rows} empty="No users yet" />
    </div>
  );
}

function CreateUserForm() {
  const qc = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'user' | 'admin'>('user');
  const [autoApprove, setAutoApprove] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);
  const mut = useMutation({
    mutationFn: () => api.createUser({ username, password, role, auto_approve: autoApprove }),
    onSuccess: (r) => {
      setMsg({ kind: 'ok', text: r.message || `Created ${username}` });
      setUsername('');
      setPassword('');
      qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e: Error) => setMsg({ kind: 'err', text: e.message }),
  });

  return (
    <div>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted">Username</label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as 'user' | 'admin')}
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoApprove}
            onChange={(e) => setAutoApprove(e.target.checked)}
          />
          Auto-approve
        </label>
        <button
          type="button"
          disabled={!username || password.length < 4 || mut.isPending}
          onClick={() => mut.mutate()}
          className="rounded bg-accent px-4 py-2 text-sm font-semibold hover:bg-accent/90
                      disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mut.isPending ? 'Creating…' : 'Create user'}
        </button>
      </div>
      {msg && (
        <div className={`mt-3 text-xs ${msg.kind === 'ok' ? 'text-ok' : 'text-danger'}`}>{msg.text}</div>
      )}
    </div>
  );
}
