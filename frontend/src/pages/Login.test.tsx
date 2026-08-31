import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import Login from './Login';

const flags = {
  oidcEnabled: false,
  oidcProvider: '',
  passwordEnabled: true,
  appVersion: '0.7.7',
};

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      loginFlags: () => ({ ...flags }),
    },
  };
});

function renderLogin(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setCsrfMeta(value: string) {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  const meta = document.createElement('meta');
  meta.setAttribute('name', 'csrf-token');
  meta.setAttribute('content', value);
  document.head.appendChild(meta);
}

beforeEach(() => {
  flags.oidcEnabled = false;
  flags.oidcProvider = '';
  flags.passwordEnabled = true;
  setCsrfMeta('test-csrf-token');
});

afterEach(() => {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
});

describe('Login', () => {
  it('renders username and password fields and a submit button', () => {
    renderLogin();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('submits a real form post to /login', () => {
    const { container } = renderLogin();
    const form = container.querySelector('form')!;
    expect(form.getAttribute('method')).toBe('post');
    expect(form.getAttribute('action')).toBe('/login');
  });

  it('mirrors the csrf meta tag into a hidden csrf_token field', () => {
    const { container } = renderLogin();
    const csrf = container.querySelector('input[name="csrf_token"]') as HTMLInputElement;
    expect(csrf).toBeTruthy();
    expect(csrf.value).toBe('test-csrf-token');
  });

  it('carries the ?next= param in the hidden next field', () => {
    const { container } = renderLogin('/login?next=%2Fwatchlist&error=1');
    const next = container.querySelector('input[name="next"]') as HTMLInputElement;
    expect(next.value).toBe('/watchlist');
  });

  it('defaults the hidden next field to / when absent from the query', () => {
    const { container } = renderLogin('/login');
    const next = container.querySelector('input[name="next"]') as HTMLInputElement;
    expect(next.value).toBe('/');
  });

  it('shows the error banner on error=1', () => {
    renderLogin('/login?next=%2Fwatchlist&error=1');
    expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
  });

  it('shows the oidc-specific message on error=oidc', () => {
    renderLogin('/login?error=oidc');
    expect(screen.getByText(/sso sign-in failed/i)).toBeInTheDocument();
  });

  it('shows no error banner without an error param', () => {
    renderLogin('/login');
    expect(screen.queryByText(/invalid credentials/i)).not.toBeInTheDocument();
  });

  it('renders the tagline', () => {
    renderLogin();
    expect(screen.getByText(/the hidden network beneath your media library/i)).toBeInTheDocument();
  });

  it('renders the Continue link when oidc is enabled, pointing at /login/oidc', () => {
    flags.oidcEnabled = true;
    flags.oidcProvider = 'Authentik';
    renderLogin('/login');
    const link = screen.getByRole('link', { name: /continue with authentik/i });
    expect(link).toHaveAttribute('href', '/login/oidc');
  });

  it('carries ?next= onto the oidc link when present', () => {
    flags.oidcEnabled = true;
    flags.oidcProvider = 'Authentik';
    renderLogin('/login?next=%2Fwatchlist');
    const link = screen.getByRole('link', { name: /continue with authentik/i });
    expect(link).toHaveAttribute('href', '/login/oidc?next=%2Fwatchlist');
  });

  it('does not render an oidc link when oidc is disabled', () => {
    renderLogin();
    expect(screen.queryByRole('link', { name: /continue with/i })).not.toBeInTheDocument();
  });

  it('hides the password form when oidc is enabled and password is disabled', () => {
    flags.oidcEnabled = true;
    flags.oidcProvider = 'Authentik';
    flags.passwordEnabled = false;
    renderLogin();
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument();
  });

  it('shows the version footer', () => {
    renderLogin();
    expect(screen.getByText(/self-hosted/i)).toBeInTheDocument();
  });
});
