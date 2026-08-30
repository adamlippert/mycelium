# UI Overhaul, Plan 1: Foundation and Shell

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the design system and application shell the other three plans assemble screens from: colour and type tokens, self-hosted fonts, an SVG icon set, seven tested primitives, and a rewritten sidebar and topbar fed by one summary endpoint.

**Architecture:** Tailwind keeps its role; only the palette changes, with a `tokens.css` alongside it for the alpha-composited surfaces Tailwind expresses badly. Primitives live one per file under `components/primitives/` and are tested with Vitest before any screen consumes them. `Layout.tsx` (289 lines, currently holding the sidebar, topbar, search, breadcrumb and region picker inline) splits into four files under `components/shell/`.

**Tech Stack:** React 18, TypeScript, Tailwind 3.4, Vite 5, React Query 5, Vitest + jsdom + @testing-library/react (added by Task 1), Flask 3 / Python 3.12 for the one endpoint.

**Spec:** `docs/superpowers/specs/2026-08-30-ui-overhaul-design.md`

**Plan 1 of 4.** Plans 2 (the eight React screens), 3 (Admin) and 4 (pre-auth cutover) follow and depend on this one.

## Global Constraints

- **Never use em-dashes**, anywhere, in code or prose. Use a comma, a colon, parentheses, or " - ". This is a project rule from `CLAUDE.md` and it applies to code comments, commit messages and documentation alike.
- **The repository is public.** No passwords, tokens, API keys or IP addresses in any commit.
- **Work on branch `feat/ui-overhaul`**, taken from `main`. Do not commit to `main`.
- **No `Co-Authored-By` lines** in commit messages.
- **`static/app/` is checked in.** The Dockerfile copies it when the npm build is skipped, so every task that changes frontend source must run `npm run build` and commit the built output.
- **Fonts are self-hosted.** Never reference `fonts.googleapis.com` or `fonts.gstatic.com`.
- **No route may ever call `location.reload()`.** `tests/test_admin_refresh.py` enforces this.
- **Every number rendered maps to a real endpoint**, or it is not rendered. Do not invent placeholder metrics.
- Run Python tests with `./.venv-sdd/bin/python -m pytest tests/ -q`. That venv has Flask and pytest but not APScheduler, so tests must not `import app`.
- `npx tsc --noEmit` has pre-existing errors in `PosterCard.tsx`, `usePluginSlots.ts` and `Watchlist.tsx`. Ignore those; only fix errors in files you touched.

## File Structure

| File | Responsibility |
|---|---|
| `frontend/vite.config.ts` | modify: add the Vitest block |
| `frontend/src/test/setup.ts` | create: jest-dom matchers, one line |
| `frontend/package.json` | modify: devDeps, `test` script |
| `frontend/tailwind.config.js` | modify: replace the palette |
| `frontend/src/design/tokens.css` | create: alpha surfaces, pill backgrounds, glow |
| `frontend/src/index.css` | modify: import tokens and fonts, scrollbar colours |
| `frontend/index.html` | modify: favicon recoloured to the new brand |
| `frontend/src/design/icons.tsx` | create: eleven nav icons, one component each |
| `frontend/src/components/primitives/Pill.tsx` | create: five state pills |
| `frontend/src/components/primitives/StatusDot.tsx` | create: dot plus glow |
| `frontend/src/components/primitives/Card.tsx` | create: surface, border, radius |
| `frontend/src/components/primitives/Chip.tsx` | create: filter chip, removable chip |
| `frontend/src/components/primitives/Toggle.tsx` | create: 38x22 switch |
| `frontend/src/components/primitives/StatTile.tsx` | create: value, label, sub, glow |
| `frontend/src/components/primitives/DataTable.tsx` | create: header, rows, empty state |
| `frontend/src/components/primitives/index.ts` | create: barrel export |
| `shell_summary.py` | create: nav counts and TorBox state, importable without Flask |
| `app.py` | modify: `GET /ui/api/shell-summary` |
| `tests/test_shell_summary.py` | create |
| `frontend/src/components/shell/NavItem.tsx` | create |
| `frontend/src/components/shell/Sidebar.tsx` | create |
| `frontend/src/components/shell/Topbar.tsx` | create |
| `frontend/src/components/shell/RegionPicker.tsx` | create: moved from `Layout.tsx` |
| `frontend/src/components/Layout.tsx` | modify: becomes a thin composition |
| `frontend/src/api.ts` | modify: `shellSummary()` |

---

### Task 1: Vitest infrastructure

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Test: `frontend/src/test/smoke.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `npm test` in `frontend/` runs Vitest. Every later task's component tests are `*.test.tsx` files beside the component.

- [ ] **Step 1: Install dependencies**

```bash
cd frontend
npm install
npm install -D vitest@^2.1.0 jsdom@^25.0.0 @testing-library/react@^16.0.0 @testing-library/jest-dom@^6.5.0 @testing-library/user-event@^14.5.0
```

- [ ] **Step 2: Add the test script**

In `frontend/package.json`, inside `"scripts"`, alongside the existing `dev`, `build` and `preview` entries:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 3: Create the setup file**

`frontend/src/test/setup.ts`:

```ts
// Registers matchers like toBeInTheDocument() and toHaveClass() on expect().
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 4: Configure Vitest**

In `frontend/vite.config.ts`, add a `test` key to the object passed to `defineConfig`, as a sibling of the existing `server` key. Add the triple-slash reference as the file's first line so TypeScript accepts the `test` key.

First line of the file:

```ts
/// <reference types="vitest" />
```

Inside `defineConfig({ ... })`:

```ts
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
```

- [ ] **Step 5: Write the smoke test**

`frontend/src/test/smoke.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

describe('the test harness', () => {
  it('renders a component and finds it in the document', () => {
    render(<p>mycelium</p>);
    expect(screen.getByText('mycelium')).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run it**

Run: `cd frontend && npm test`
Expected: PASS, 1 test.

- [ ] **Step 7: Confirm the existing suites are untouched**

Run: `./.venv-sdd/bin/python -m pytest tests/ -q && node --test tests/js/filter_rules.test.js`
Expected: 443 passed, and 34 JS tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/
git commit -m "test(frontend): add vitest so components can be tested

Nothing in the 4950 lines of frontend source has ever had a test. This
project rewrites most of it and ports the Jinja admin into it, where a
dropped control would otherwise fail silently."
```

---

### Task 2: Design tokens and self-hosted fonts

**Files:**
- Modify: `frontend/tailwind.config.js`
- Create: `frontend/src/design/tokens.css`
- Modify: `frontend/src/index.css`
- Modify: `frontend/index.html:8` (the favicon data URI)
- Test: `frontend/src/design/tokens.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: Tailwind classes `bg-bg`, `bg-sidebar`, `bg-card`, `border-border`, `text-accent`, `text-accent-light`, `text-accent-pale`, `text-ok`, `text-warn`, `text-danger`, `text-body`, `text-muted`. CSS custom properties `--pill-ready-bg`, `--pill-ready-fg`, `--pill-ready-border` and the same triple for `materializing`, `queued`, `failed`, `lazy`; plus `--dot-ok`, `--dot-warn`, `--dot-danger`.

- [ ] **Step 1: Install the fonts**

```bash
cd frontend
npm install @fontsource/inter@^5.1.0 @fontsource/jetbrains-mono@^5.1.0
```

These packages ship woff2 files and are bundled by Vite, so nothing is fetched from Google at runtime.

- [ ] **Step 2: Write the failing test**

`frontend/src/design/tokens.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p: string) => readFileSync(resolve(__dirname, p), 'utf8');
const tokens = () => read('./tokens.css');
const tailwind = () => read('../../tailwind.config.js');
const indexCss = () => read('../index.css');

describe('the palette', () => {
  it('uses the new brand purple, not the old indigo', () => {
    expect(tailwind()).toContain('#6152df');
    expect(tailwind()).not.toContain('#6366f1');
  });

  it('drops the retired tokens', () => {
    // These are unquoted keys in the current config, so matching the bare
    // name in quotes would pass even if the key survived. Match the key.
    const config = tailwind();
    for (const retired of ['accent-2', 'teal', 'mint', 'amber', 'info']) {
      const key = new RegExp(`(^|\\s|')${retired}'?\\s*:`, 'm');
      expect(config, `${retired} is still defined`).not.toMatch(key);
    }
  });

  it('sets the page and sidebar grounds', () => {
    expect(tailwind()).toContain('#070707');
    expect(tailwind()).toContain('#0b0b0b');
  });
});

describe('the pill tokens', () => {
  const STATES = ['ready', 'materializing', 'queued', 'failed', 'lazy'];

  it('defines a background, foreground and border for every state', () => {
    const css = tokens();
    for (const s of STATES) {
      expect(css).toContain(`--pill-${s}-bg:`);
      expect(css).toContain(`--pill-${s}-fg:`);
      expect(css).toContain(`--pill-${s}-border:`);
    }
  });

  it('composites the pill backgrounds over the dark ground', () => {
    // Flat hex here would look wrong on a card that is not the page colour.
    expect(tokens()).toMatch(/--pill-ready-bg:\s*rgba\(/);
  });
});

describe('fonts', () => {
  it('are self-hosted, never fetched from Google', () => {
    const css = indexCss();
    expect(css).toContain('@fontsource/inter');
    expect(css).toContain('@fontsource/jetbrains-mono');
    expect(css).not.toContain('fonts.googleapis.com');
    expect(css).not.toContain('fonts.gstatic.com');
  });
});
```

- [ ] **Step 2b: Run it to verify it fails**

Run: `cd frontend && npm test -- tokens`
Expected: FAIL, `tokens.css` does not exist.

- [ ] **Step 3: Replace the Tailwind palette**

`frontend/tailwind.config.js`, replacing the whole `colors` object:

```js
      colors: {
        bg: '#070707',
        sidebar: '#0b0b0b',
        card: '#0f0f0f',
        'card-raised': '#151515',
        border: 'rgba(255,255,255,0.09)',
        accent: '#6152df',
        'accent-light': '#9f92ff',
        'accent-pale': '#c7c2ff',
        ok: '#7bd0a7',
        warn: '#dacd8a',
        danger: '#e48181',
        body: '#e6e6e6',
        muted: 'rgba(255,255,255,0.5)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
```

- [ ] **Step 4: Create the tokens**

`frontend/src/design/tokens.css`:

```css
/* Alpha-composited surfaces. These sit over varying card grounds, so they
   cannot be flat hex the way the Tailwind palette is. */
:root {
  --pill-ready-bg: rgba(37, 140, 96, 0.14);
  --pill-ready-fg: #7bd0a7;
  --pill-ready-border: rgba(87, 161, 129, 0.28);

  --pill-materializing-bg: rgba(97, 82, 223, 0.16);
  --pill-materializing-fg: #c7c2ff;
  --pill-materializing-border: rgba(159, 146, 255, 0.3);

  --pill-queued-bg: rgba(198, 178, 83, 0.13);
  --pill-queued-fg: #dacd8a;
  --pill-queued-border: rgba(198, 178, 83, 0.28);

  --pill-failed-bg: rgba(209, 71, 71, 0.14);
  --pill-failed-fg: #e48181;
  --pill-failed-border: rgba(228, 129, 129, 0.28);

  --pill-lazy-bg: rgba(255, 255, 255, 0.05);
  --pill-lazy-fg: rgba(255, 255, 255, 0.55);
  --pill-lazy-border: rgba(255, 255, 255, 0.1);

  --dot-ok: #57a181;
  --dot-warn: #c6b253;
  --dot-danger: #d14747;

  --surface-subtle: rgba(255, 255, 255, 0.04);
  --surface-hover: rgba(255, 255, 255, 0.06);
  --nav-active: rgba(97, 82, 223, 0.16);
}
```

- [ ] **Step 5: Wire the tokens and fonts in**

`frontend/src/index.css`, replacing its current contents:

```css
@import '@fontsource/inter/400.css';
@import '@fontsource/inter/500.css';
@import '@fontsource/inter/600.css';
@import '@fontsource/inter/700.css';
@import '@fontsource/jetbrains-mono/400.css';
@import '@fontsource/jetbrains-mono/500.css';
@import './design/tokens.css';

@tailwind base;
@tailwind components;
@tailwind utilities;

:root { color-scheme: dark; }
html, body, #root { height: 100%; }
body {
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: #070707; }
::-webkit-scrollbar-thumb { background: #363636; border-radius: 9999px; }
::-webkit-scrollbar-thumb:hover { background: #484848; }

@layer utilities {
  .scrollbar-hidden::-webkit-scrollbar { display: none; }
  .scrollbar-hidden { scrollbar-width: none; }
}
```

- [ ] **Step 6: Recolour the favicon**

In `frontend/index.html`, the favicon data URI currently uses the retired cyan and teal. Replace every `%2322d3ee` with `%239f92ff`, every `%230d9488` with `%236152df`, and every `%235eead4` with `%23c7c2ff`. Leave the geometry alone.

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npm test -- tokens`
Expected: PASS, all four describes.

- [ ] **Step 8: Confirm the app still builds**

Run: `cd frontend && npm run build`
Expected: build succeeds, output in `../static/app/`.

Open `static/app/index.html` and confirm no `fonts.googleapis.com` appears anywhere in `static/app/`:

Run: `grep -r "fonts.googleapis\|fonts.gstatic" static/app/ ; echo "exit=$?"`
Expected: no matches, `exit=1`.

- [ ] **Step 9: Commit**

```bash
git add frontend/ static/app/
git commit -m "feat(ui): new palette, self-hosted fonts, alpha surface tokens

Brand moves from indigo to purple and the ground goes near-black. The
pill and dot colours are alpha over a dark ground rather than flat hex,
so they live in tokens.css instead of the Tailwind palette.

Inter and JetBrains Mono ship from node_modules via @fontsource. This is
a self-hosted application; its users should not make requests to Google
to render a page."
```

---

### Task 3: The icon set

**Files:**
- Create: `frontend/src/design/icons.tsx`
- Test: `frontend/src/design/icons.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `export type IconName = 'discover' | 'library' | 'watchlist' | 'search' | 'requests' | 'wanted' | 'settings' | 'admin' | 'manual' | 'setup' | 'login'` and `export function Icon({ name, className }: { name: IconName; className?: string }): JSX.Element`. Task 7 renders nav icons through this.

- [ ] **Step 1: Write the failing test**

`frontend/src/design/icons.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Icon, ICON_NAMES } from './icons';

describe('Icon', () => {
  it('renders every name as an svg with path data', () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      const svg = container.querySelector('svg');
      expect(svg, `${name} rendered no svg`).not.toBeNull();
      expect(svg!.querySelector('path')?.getAttribute('d'), `${name} has no path data`).toBeTruthy();
    }
  });

  it('covers exactly the eleven navigable screens', () => {
    expect([...ICON_NAMES].sort()).toEqual([
      'admin', 'discover', 'library', 'login', 'manual', 'requests',
      'search', 'settings', 'setup', 'wanted', 'watchlist',
    ]);
  });

  it('inherits colour so the active nav state can tint it', () => {
    const { container } = render(<Icon name="discover" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('currentColor');
  });

  it('passes className through for sizing', () => {
    const { container } = render(<Icon name="library" className="w-4 h-4" />);
    expect(container.querySelector('svg')).toHaveClass('w-4', 'h-4');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- icons`
Expected: FAIL, cannot resolve `./icons`.

- [ ] **Step 3: Implement**

`frontend/src/design/icons.tsx`. The path data is lifted verbatim from the mockup's `SCREENS` array in `docs/superpowers/specs/assets/2026-08-30-ui-overhaul-mockup.html`:

```tsx
export const ICON_NAMES = [
  'discover', 'library', 'watchlist', 'search', 'requests',
  'wanted', 'settings', 'admin', 'manual', 'setup', 'login',
] as const;

export type IconName = (typeof ICON_NAMES)[number];

const PATHS: Record<IconName, string> = {
  discover: 'M12 3a9 9 0 100 18 9 9 0 000-18zM15.5 8.5l-2.2 4.8-4.8 2.2 2.2-4.8 4.8-2.2z',
  library: 'M4 4h7v16H6a2 2 0 01-2-2V4zm9 0h7v14a2 2 0 01-2 2h-5V4z',
  watchlist: 'M12 4l2.5 5.2 5.5.8-4 3.9.9 5.6-4.9-2.7-4.9 2.7.9-5.6-4-3.9 5.5-.8z',
  search: 'M16.5 16.5L21 21M17 11a6 6 0 11-12 0 6 6 0 0112 0z',
  requests: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  wanted: 'M12 7v5l4 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  settings: 'M4 8h9M17 8h3M4 16h4M12 16h8M14 5v6M9 13v6',
  admin: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.6 14.6a1.7 1.7 0 00.3 1.9 2 2 0 11-2.8 2.8 1.7 1.7 0 00-2.9 1.2 2 2 0 11-4 0 1.7 1.7 0 00-2.9-1.2 2 2 0 11-2.8-2.8 1.7 1.7 0 00-1.2-2.9 2 2 0 110-4 1.7 1.7 0 001.2-2.9 2 2 0 112.8-2.8A1.7 1.7 0 0010.2 3a2 2 0 114 0 1.7 1.7 0 002.9 1.2 2 2 0 112.8 2.8 1.7 1.7 0 001.2 2.9 2 2 0 110 4 1.7 1.7 0 00-1.5 1.7z',
  manual: 'M4 4h7v16H6a2 2 0 01-2-2V4zm9 0h7v14a2 2 0 01-2 2h-5V4zM8 8h3M8 12h3',
  setup: 'M5 7h14M5 12h9M5 17h6M17 15l2 2 3-4',
  login: 'M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l-5-5 5-5M5 12h9',
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test -- icons`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/design/icons.tsx frontend/src/design/icons.test.tsx
git commit -m "feat(ui): svg icon set replacing the nav emoji

Eleven icons, path data taken from the mockup. Stroke uses currentColor
so the active nav state tints the icon with the label."
```

---

### Task 4: Primitives, part one (Pill, StatusDot, Card)

**Files:**
- Create: `frontend/src/components/primitives/Pill.tsx`
- Create: `frontend/src/components/primitives/StatusDot.tsx`
- Create: `frontend/src/components/primitives/Card.tsx`
- Create: `frontend/src/components/primitives/index.ts`
- Test: `frontend/src/components/primitives/primitives.test.tsx`

**Interfaces:**
- Consumes: the CSS custom properties from Task 2.
- Produces:
  - `export type PillState = 'ready' | 'materializing' | 'queued' | 'failed' | 'lazy'`
  - `export function Pill({ state, children }: { state: PillState; children: React.ReactNode }): JSX.Element`
  - `export function StatusDot({ tone }: { tone: 'ok' | 'warn' | 'danger' }): JSX.Element`
  - `export function Card({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element`
  - `frontend/src/components/primitives/index.ts` re-exports every primitive; later tasks import from `@/components/primitives`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/primitives/primitives.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Pill, StatusDot, Card, PILL_STATES } from './index';

describe('Pill', () => {
  it('renders its label', () => {
    render(<Pill state="ready">Ready</Pill>);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('drives colour from the state token, not a hardcoded hex', () => {
    const { container } = render(<Pill state="failed">Failed</Pill>);
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.background).toContain('--pill-failed-bg');
    expect(el.style.color).toContain('--pill-failed-fg');
  });

  it('supports all five states without falling back', () => {
    for (const state of PILL_STATES) {
      const { container } = render(<Pill state={state}>x</Pill>);
      const el = container.firstElementChild as HTMLElement;
      expect(el.style.background, `${state} has no background`).toContain(`--pill-${state}-bg`);
    }
  });
});

describe('StatusDot', () => {
  it('tints and glows in the same tone', () => {
    const { container } = render(<StatusDot tone="warn" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.background).toContain('--dot-warn');
    expect(el.style.boxShadow).toContain('--dot-warn');
  });
});

describe('Card', () => {
  it('renders children inside a bordered surface', () => {
    render(<Card>contents</Card>);
    const el = screen.getByText('contents');
    expect(el).toHaveClass('bg-card', 'border', 'border-border');
  });

  it('merges an extra className rather than replacing its own', () => {
    render(<Card className="mb-4">contents</Card>);
    expect(screen.getByText('contents')).toHaveClass('bg-card', 'mb-4');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- primitives`
Expected: FAIL, cannot resolve `./index`.

- [ ] **Step 3: Implement Pill**

`frontend/src/components/primitives/Pill.tsx`:

```tsx
export const PILL_STATES = ['ready', 'materializing', 'queued', 'failed', 'lazy'] as const;

export type PillState = (typeof PILL_STATES)[number];

export function Pill({ state, children }: { state: PillState; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1
                 text-[10px] font-medium leading-none tracking-wide"
      style={{
        background: `var(--pill-${state}-bg)`,
        color: `var(--pill-${state}-fg)`,
        borderColor: `var(--pill-${state}-border)`,
      }}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 4: Implement StatusDot**

`frontend/src/components/primitives/StatusDot.tsx`:

```tsx
export function StatusDot({ tone }: { tone: 'ok' | 'warn' | 'danger' }) {
  return (
    <span
      className="block h-[7px] w-[7px] flex-none rounded-full"
      style={{
        background: `var(--dot-${tone})`,
        boxShadow: `0 0 8px var(--dot-${tone})`,
      }}
    />
  );
}
```

- [ ] **Step 5: Implement Card**

`frontend/src/components/primitives/Card.tsx`:

```tsx
export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-card border border-border rounded-xl p-4 ${className}`.trim()}>
      {children}
    </div>
  );
}
```

- [ ] **Step 6: Create the barrel**

`frontend/src/components/primitives/index.ts`:

```ts
export { Pill, PILL_STATES } from './Pill';
export type { PillState } from './Pill';
export { StatusDot } from './StatusDot';
export { Card } from './Card';
```

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npm test -- primitives`
Expected: PASS, 6 tests.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/primitives/
git commit -m "feat(ui): Pill, StatusDot and Card primitives

Pill colours come from the CSS custom properties rather than hardcoded
hex, so a state's colour is defined once and every screen agrees."
```

---

### Task 5: Primitives, part two (Chip, Toggle, StatTile, DataTable)

**Files:**
- Create: `frontend/src/components/primitives/Chip.tsx`
- Create: `frontend/src/components/primitives/Toggle.tsx`
- Create: `frontend/src/components/primitives/StatTile.tsx`
- Create: `frontend/src/components/primitives/DataTable.tsx`
- Modify: `frontend/src/components/primitives/index.ts`
- Test: `frontend/src/components/primitives/interactive.test.tsx`

**Interfaces:**
- Consumes: `Card` from Task 4.
- Produces:
  - `export function Chip({ label, selected, onClick, onRemove }: { label: string; selected?: boolean; onClick?: () => void; onRemove?: () => void }): JSX.Element`
  - `export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (next: boolean) => void; label: string }): JSX.Element`
  - `export function StatTile({ value, label, sub, glow }: { value: string; label: string; sub?: string; glow?: 'accent' | 'ok' | 'warn' | 'danger' }): JSX.Element`
  - `export function DataTable<T>({ columns, rows, empty }: { columns: { key: string; header: string; render: (row: T) => React.ReactNode; align?: 'left' | 'right' }[]; rows: T[]; empty: string }): JSX.Element`

Plan 2 uses `Chip` for Library and Search filters, `DataTable` for Library, Requests and Wanted, and `StatTile` for Library and Requests. Plan 3 uses `Toggle` for Settings and Filter rules.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/primitives/interactive.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { Chip, Toggle, StatTile, DataTable } from './index';

describe('Chip', () => {
  it('calls onClick when pressed', async () => {
    const onClick = vi.fn();
    render(<Chip label="Movies" onClick={onClick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Movies' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('marks the selected chip for assistive tech, not just visually', () => {
    render(<Chip label="Movies" selected onClick={() => {}} />);
    expect(screen.getByRole('button', { name: 'Movies' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows a remove control only when onRemove is given', async () => {
    const onRemove = vi.fn();
    const { rerender } = render(<Chip label="1080p" />);
    expect(screen.queryByRole('button', { name: /remove 1080p/i })).toBeNull();

    rerender(<Chip label="1080p" onRemove={onRemove} />);
    await userEvent.click(screen.getByRole('button', { name: /remove 1080p/i }));
    expect(onRemove).toHaveBeenCalledOnce();
  });
});

describe('Toggle', () => {
  it('reports its state through the checkbox role', () => {
    render(<Toggle checked label="Enabled" onChange={() => {}} />);
    expect(screen.getByRole('checkbox', { name: 'Enabled' })).toBeChecked();
  });

  it('emits the inverted value when clicked', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Enabled" onChange={onChange} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Enabled' }));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe('StatTile', () => {
  it('renders value, label and sub-line', () => {
    render(<StatTile value="1,284" label="Titles" sub="+18 this week" />);
    expect(screen.getByText('1,284')).toBeInTheDocument();
    expect(screen.getByText('Titles')).toBeInTheDocument();
    expect(screen.getByText('+18 this week')).toBeInTheDocument();
  });

  it('omits the sub-line entirely when there is none', () => {
    const { container } = render(<StatTile value="6" label="Failures" />);
    expect(container.textContent).toBe('6Failures');
  });
});

describe('DataTable', () => {
  type Row = { title: string; year: number };
  const columns = [
    { key: 'title', header: 'Title', render: (r: Row) => r.title },
    { key: 'year', header: 'Year', render: (r: Row) => String(r.year), align: 'right' as const },
  ];

  it('renders a header cell per column and a row per item', () => {
    render(<DataTable columns={columns} rows={[{ title: 'Dune', year: 2021 }]} empty="Nothing" />);
    expect(screen.getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['Title', 'Year']);
    expect(screen.getByText('Dune')).toBeInTheDocument();
    expect(screen.getByText('2021')).toBeInTheDocument();
  });

  it('shows the empty message instead of a bare table', () => {
    render(<DataTable columns={columns} rows={[]} empty="No repair history yet" />);
    expect(screen.getByText('No repair history yet')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- interactive`
Expected: FAIL, `Chip` is not exported.

- [ ] **Step 3: Implement Chip**

`frontend/src/components/primitives/Chip.tsx`:

```tsx
export function Chip({
  label,
  selected = false,
  onClick,
  onRemove,
}: {
  label: string;
  selected?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium ${
        selected
          ? 'bg-accent border-accent text-white'
          : 'border-border text-muted hover:text-body'
      }`}
      style={selected ? undefined : { background: 'var(--surface-subtle)' }}
    >
      <button type="button" onClick={onClick} aria-pressed={onClick ? selected : undefined}>
        {label}
      </button>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${label}`} className="opacity-60 hover:opacity-100">
          &times;
        </button>
      )}
    </span>
  );
}
```

- [ ] **Step 4: Implement Toggle**

`frontend/src/components/primitives/Toggle.tsx`:

```tsx
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        className="sr-only"
        checked={checked}
        aria-label={label}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        className={`flex h-[22px] w-[38px] flex-none items-center rounded-full p-[3px] transition-all ${
          checked ? 'bg-accent justify-end' : 'justify-start'
        }`}
        style={checked ? undefined : { background: 'rgba(255,255,255,0.1)' }}
      >
        <span
          className="block h-4 w-4 rounded-full"
          style={{ background: checked ? '#fff' : 'rgba(255,255,255,0.55)' }}
        />
      </span>
    </label>
  );
}
```

- [ ] **Step 5: Implement StatTile**

`frontend/src/components/primitives/StatTile.tsx`:

```tsx
const GLOW: Record<string, string> = {
  accent: 'rgba(97,82,223,0.5)',
  ok: 'rgba(37,140,96,0.4)',
  warn: 'rgba(198,178,83,0.4)',
  danger: 'rgba(209,71,71,0.4)',
};

export function StatTile({
  value,
  label,
  sub,
  glow,
}: {
  value: string;
  label: string;
  sub?: string;
  glow?: 'accent' | 'ok' | 'warn' | 'danger';
}) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-card p-4">
      {glow && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-5 -top-8 h-20 w-28 rounded-full opacity-50 blur-[38px]"
          style={{ background: GLOW[glow] }}
        />
      )}
      <div className="relative font-mono text-2xl font-semibold text-body">{value}</div>
      <div className="relative mt-1 text-xs text-muted">{label}</div>
      {sub && <div className="relative mt-1 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}
```

- [ ] **Step 6: Implement DataTable**

`frontend/src/components/primitives/DataTable.tsx`:

```tsx
export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  align?: 'left' | 'right';
};

export function DataTable<T>({
  columns,
  rows,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  empty: string;
}) {
  if (!rows.length) {
    return <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted">{empty}</div>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 text-[11px] font-medium uppercase tracking-wider text-muted ${
                  c.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.align === 'right' ? 'text-right' : 'text-left'}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 7: Extend the barrel**

Append to `frontend/src/components/primitives/index.ts`:

```ts
export { Chip } from './Chip';
export { Toggle } from './Toggle';
export { StatTile } from './StatTile';
export { DataTable } from './DataTable';
export type { Column } from './DataTable';
```

- [ ] **Step 8: Run the tests**

Run: `cd frontend && npm test`
Expected: PASS, all primitive and icon tests.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/primitives/
git commit -m "feat(ui): Chip, Toggle, StatTile and DataTable primitives

Chip carries aria-pressed and Toggle exposes a real checkbox, so the
selected and on states are reachable without looking at colour."
```

---

### Task 6: The shell summary endpoint

**Files:**
- Create: `shell_summary.py`
- Modify: `app.py` (beside `ui_api_repair`, around line 1121)
- Modify: `frontend/src/api.ts`
- Test: `tests/test_shell_summary.py`

**Interfaces:**
- Consumes: `db`, `stats`, `torbox`.
- Produces:
  - Python: `shell_summary.get_shell_summary() -> dict` returning `{"counts": {"watchlist": int, "requests": int, "wanted": int}, "torbox": {"state": str, "label": str}}` where `state` is one of `"ok"`, `"degraded"`, `"down"`.
  - HTTP: `GET /ui/api/shell-summary`.
  - TypeScript: `api.shellSummary(): Promise<ShellSummary>` with `export type ShellSummary = { counts: { watchlist: number; requests: number; wanted: number }; torbox: { state: 'ok' | 'degraded' | 'down'; label: string } }`.

Task 7 consumes `api.shellSummary` for the nav counts; Task 8 for the TorBox pill.

- [ ] **Step 1: Read how TorBox reports rate-limit pressure**

Run: `grep -n "def \|RATE\|429\|budget" torbox.py | head -40`

Identify the existing function that reports remaining createtorrent budget. The implementation below calls it `torbox.rate_limit_status()`; if the real name differs, use the real one and keep the returned `state` vocabulary unchanged.

- [ ] **Step 2: Write the failing test**

`tests/test_shell_summary.py`:

```python
"""The sidebar counts and the topbar TorBox pill render on every page.

Three separate calls for data that is always fetched together is three
round trips per navigation, so they come from one endpoint.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import shell_summary


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def test_the_shape_is_stable_on_an_empty_install():
    """The sidebar renders before any data exists. Missing keys would render
    'undefined' badges rather than nothing."""
    d = shell_summary.get_shell_summary()
    assert set(d) == {"counts", "torbox"}
    assert set(d["counts"]) == {"watchlist", "requests", "wanted"}
    assert set(d["torbox"]) == {"state", "label"}
    assert d["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}


def test_torbox_state_is_one_of_three_values(monkeypatch):
    d = shell_summary.get_shell_summary()
    assert d["torbox"]["state"] in {"ok", "degraded", "down"}


def test_a_healthy_torbox_reads_online(monkeypatch):
    monkeypatch.setattr(shell_summary, "_torbox_state", lambda: ("ok", "TorBox online"))
    d = shell_summary.get_shell_summary()
    assert d["torbox"] == {"state": "ok", "label": "TorBox online"}


def test_torbox_failures_never_break_the_sidebar(monkeypatch):
    """The counts are the point of this endpoint. A TorBox outage must not
    take the navigation down with it."""
    def boom():
        raise RuntimeError("torbox unreachable")

    monkeypatch.setattr(shell_summary, "_torbox_state", boom)
    d = shell_summary.get_shell_summary()
    assert d["torbox"]["state"] == "down"
    assert d["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}


def test_the_endpoint_is_registered_and_authenticated():
    """Auth is a global before_request hook on /ui/api/, so the route needs no
    decorator; this pins that it lives under that prefix."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/shell-summary")' in src
    assert "shell_summary.get_shell_summary()" in src
```

- [ ] **Step 3: Run it to verify it fails**

Run: `./.venv-sdd/bin/python -m pytest tests/test_shell_summary.py -q`
Expected: FAIL, `No module named 'shell_summary'`.

- [ ] **Step 4: Implement the module**

`shell_summary.py`:

```python
"""Data the application shell needs on every page.

The sidebar counts and the topbar TorBox pill are fetched together on every
navigation, so they are served together rather than as three round trips.
"""
import logging

import db
import torbox

log = logging.getLogger(__name__)


def _torbox_state() -> tuple[str, str]:
    """('ok' | 'degraded' | 'down', human label)."""
    status = torbox.rate_limit_status()
    if status.get("blocked"):
        return "down", "TorBox rate limited"
    if status.get("near_limit"):
        return "degraded", "TorBox near its limit"
    return "ok", "TorBox online"


def get_shell_summary() -> dict:
    counts = {
        "watchlist": len(db.get_watchlist()),
        "requests": len(db.get_pending_user_requests()),
        "wanted": len([w for w in db.get_all_wanted_episodes() if w["status"] == "wanted"]),
    }

    try:
        state, label = _torbox_state()
    except Exception as exc:
        # The counts are the point of this endpoint. A TorBox outage must not
        # take the navigation down with it.
        log.warning("shell summary: torbox state unavailable: %s", exc)
        state, label = "down", "TorBox unreachable"

    return {"counts": counts, "torbox": {"state": state, "label": label}}
```

If `db.get_watchlist()` or `db.get_pending_user_requests()` do not exist under those names, run `grep -n "def get_watchlist\|def get_pending\|watchlist" db.py` and use the real accessors. Do not add new SQL; every count here already has a reader.

- [ ] **Step 5: Add the route**

In `app.py`, immediately after the `ui_api_repair` handler:

```python
@app.get("/ui/api/shell-summary")
def ui_api_shell_summary():
    """Sidebar counts and the topbar TorBox pill, in one call."""
    return jsonify(shell_summary.get_shell_summary())
```

Add `import shell_summary` beside the other module imports at the top of `app.py`.

- [ ] **Step 6: Run the tests**

Run: `./.venv-sdd/bin/python -m pytest tests/test_shell_summary.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 7: Add the client**

In `frontend/src/api.ts`, beside the other `api` members:

```ts
export type ShellSummary = {
  counts: { watchlist: number; requests: number; wanted: number };
  torbox: { state: 'ok' | 'degraded' | 'down'; label: string };
};
```

and inside the `api` object:

```ts
  shellSummary: (): Promise<ShellSummary> => get('/ui/api/shell-summary'),
```

Match the surrounding style: if the file uses a helper other than `get`, use that one.

- [ ] **Step 8: Run the full Python suite**

Run: `./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: 448 passed.

- [ ] **Step 9: Commit**

```bash
git add shell_summary.py app.py tests/test_shell_summary.py frontend/src/api.ts
git commit -m "feat(api): one shell-summary call for nav counts and TorBox state

Both render on every page. Fetching them separately is three round trips
per navigation. A TorBox failure degrades the pill and leaves the counts
intact, because the counts are what the sidebar is for."
```

---

### Task 7: Sidebar and NavItem

**Files:**
- Create: `frontend/src/components/shell/NavItem.tsx`
- Create: `frontend/src/components/shell/Sidebar.tsx`
- Test: `frontend/src/components/shell/Sidebar.test.tsx`

**Interfaces:**
- Consumes: `Icon`, `IconName` (Task 3); `api.shellSummary`, `ShellSummary` (Task 6).
- Produces:
  - `export type NavEntry = { to: string; label: string; icon: IconName; exact?: boolean; countKey?: 'watchlist' | 'requests' | 'wanted' }`
  - `export const NAV_GROUPS: { title: string; items: NavEntry[] }[]`
  - `export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }): JSX.Element`

Task 9 renders `Sidebar`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/shell/Sidebar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Sidebar, NAV_GROUPS } from './Sidebar';

vi.mock('../../api', () => ({
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 38, requests: 3, wanted: 11 },
      torbox: { state: 'ok', label: 'TorBox online' },
    }),
    session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
  },
}));

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Sidebar open onNavigate={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('NAV_GROUPS', () => {
  it('puts Settings under Manage, not Browse', () => {
    const browse = NAV_GROUPS.find((g) => g.title === 'Browse')!;
    const manage = NAV_GROUPS.find((g) => g.title === 'Manage')!;
    expect(browse.items.map((i) => i.label)).not.toContain('Settings');
    expect(manage.items.map((i) => i.label)).toContain('Settings');
  });

  it('covers every navigable route exactly once', () => {
    const tos = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.to));
    expect(tos).toEqual([
      '/', '/library', '/watchlist', '/search', '/requests', '/wanted',
      '/settings', '/admin', '/manual',
    ]);
    expect(new Set(tos).size).toBe(tos.length);
  });

  it('uses icon names, never emoji', () => {
    for (const item of NAV_GROUPS.flatMap((g) => g.items)) {
      expect(item.icon).toMatch(/^[a-z]+$/);
    }
  });
});

describe('Sidebar', () => {
  it('renders every navigation label', async () => {
    renderSidebar();
    for (const label of ['Discover', 'Library', 'Watchlist', 'Search', 'My Requests', 'Wanted']) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it('shows live counts beside the three routes that have them', async () => {
    renderSidebar();
    expect(await screen.findByText('38')).toBeInTheDocument();
    expect(await screen.findByText('11')).toBeInTheDocument();
  });

  it('renders no count badge before the summary arrives', () => {
    const { container } = renderSidebar();
    expect(container.textContent).not.toContain('undefined');
    expect(container.textContent).not.toContain('NaN');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Sidebar`
Expected: FAIL, cannot resolve `./Sidebar`.

- [ ] **Step 3: Implement NavItem**

`frontend/src/components/shell/NavItem.tsx`:

```tsx
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
```

- [ ] **Step 4: Implement Sidebar**

`frontend/src/components/shell/Sidebar.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import type { IconName } from '../../design/icons';
import { NavItem } from './NavItem';

export type NavEntry = {
  to: string;
  label: string;
  icon: IconName;
  exact?: boolean;
  countKey?: 'watchlist' | 'requests' | 'wanted';
};

export const NAV_GROUPS: { title: string; items: NavEntry[] }[] = [
  {
    title: 'Browse',
    items: [
      { to: '/', label: 'Discover', icon: 'discover', exact: true },
      { to: '/library', label: 'Library', icon: 'library' },
      { to: '/watchlist', label: 'Watchlist', icon: 'watchlist', countKey: 'watchlist' },
      { to: '/search', label: 'Search', icon: 'search' },
      { to: '/requests', label: 'My Requests', icon: 'requests', countKey: 'requests' },
      { to: '/wanted', label: 'Wanted', icon: 'wanted', countKey: 'wanted' },
    ],
  },
  {
    title: 'Manage',
    items: [
      { to: '/settings', label: 'Settings', icon: 'settings' },
      { to: '/admin', label: 'Admin', icon: 'admin' },
      { to: '/manual', label: 'Manual', icon: 'manual' },
    ],
  },
];

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { data: summary } = useQuery({
    queryKey: ['shell-summary'],
    queryFn: api.shellSummary,
    staleTime: 60_000,
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session, staleTime: 60_000 });

  const user = session?.user;
  const initials = (user?.username || '?').slice(0, 2).toUpperCase();

  return (
    <aside
      className={`fixed left-0 top-0 z-40 flex h-screen w-[248px] flex-none flex-col border-r
                  border-border bg-sidebar transition-transform duration-200 lg:sticky
                  ${open ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}
    >
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-5">
        <span className="font-mono text-lg font-bold tracking-wide text-white">
          myc<span className="text-accent-pale">3</span>l<span className="text-accent-pale">1</span>um
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-2">
            <div className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted">
              {group.title}
            </div>
            {group.items.map((item) => (
              <NavItem
                key={item.to}
                to={item.to}
                label={item.label}
                icon={item.icon}
                exact={item.exact}
                count={item.countKey ? summary?.counts[item.countKey] : undefined}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        {user ? (
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg border border-border
                             font-mono text-[11px] text-accent-pale"
                  style={{ background: 'rgba(97,82,223,0.2)' }}>
              {initials}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs text-body">{user.username}</span>
              <span className="block text-[10px] text-muted">
                {user.role === 'admin' ? 'Administrator' : 'User'}
              </span>
            </span>
            <a href="/logout" className="ml-auto text-[11px] text-muted hover:text-body">Log out</a>
          </div>
        ) : (
          <a href="/login" className="text-xs text-muted hover:text-body">Sign in</a>
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test -- Sidebar`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/shell/
git commit -m "feat(ui): sidebar with svg icons, live counts and a user card

248px, Settings moves from Browse to Manage, and the three routes with
a backlog carry their count from the shell-summary endpoint. A count is
absent rather than zero until the summary arrives, so the badge never
flashes a wrong number."
```

---

### Task 8: Topbar and RegionPicker

**Files:**
- Create: `frontend/src/components/shell/RegionPicker.tsx`
- Create: `frontend/src/components/shell/Topbar.tsx`
- Test: `frontend/src/components/shell/Topbar.test.tsx`

**Interfaces:**
- Consumes: `Pill` (Task 4); `api.shellSummary` (Task 6).
- Produces:
  - `export function RegionPicker({ region }: { region: string }): JSX.Element`, moved verbatim in behaviour from `Layout.tsx` including its 20-entry `REGIONS` list and its React Query invalidations.
  - `export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }): JSX.Element`
  - `export const CRUMBS: Record<string, string>`

- [ ] **Step 1: Move RegionPicker**

Cut `REGIONS` and the `RegionPicker` function out of `frontend/src/components/Layout.tsx` into `frontend/src/components/shell/RegionPicker.tsx` unchanged, exporting `RegionPicker`. Keep every `invalidateQueries` call exactly as it is: changing region must still refresh trending, popular, top-rated, now-playing, upcoming, providers and by-provider.

Restyle only the trigger button:

```tsx
      className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-sm
                 transition hover:border-accent-light/50"
```

- [ ] **Step 2: Write the failing test**

`frontend/src/components/shell/Topbar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Topbar, CRUMBS } from './Topbar';

vi.mock('../../api', () => ({
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 0, requests: 0, wanted: 0 },
      torbox: { state: 'degraded', label: 'TorBox near its limit' },
    }),
    session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin', region: 'NL' } }),
  },
}));

function renderTopbar(path = '/library') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Topbar onOpenMenu={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CRUMBS', () => {
  it('names every navigable route', () => {
    for (const path of ['/', '/library', '/watchlist', '/search', '/requests', '/wanted', '/settings', '/admin', '/manual']) {
      expect(CRUMBS[path], `no crumb for ${path}`).toBeTruthy();
    }
  });
});

describe('Topbar', () => {
  it('shows the MYCELIUM breadcrumb and the current page', async () => {
    renderTopbar('/library');
    expect(screen.getByText('MYCELIUM')).toBeInTheDocument();
    expect(await screen.findAllByText('Library')).not.toHaveLength(0);
  });

  it('shows the TorBox state from the summary, not a hardcoded label', async () => {
    renderTopbar();
    expect(await screen.findByText('TorBox near its limit')).toBeInTheDocument();
  });

  it('advertises the keyboard shortcut on the search field', () => {
    renderTopbar();
    expect(screen.getByText('⌘K')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npm test -- Topbar`
Expected: FAIL, cannot resolve `./Topbar`.

- [ ] **Step 4: Implement Topbar**

`frontend/src/components/shell/Topbar.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Pill } from '../primitives';
import { RegionPicker } from './RegionPicker';

export const CRUMBS: Record<string, string> = {
  '/': 'Discover',
  '/library': 'Library',
  '/watchlist': 'Watchlist',
  '/search': 'Search',
  '/requests': 'My Requests',
  '/wanted': 'Wanted',
  '/settings': 'Settings',
  '/admin': 'Admin',
  '/manual': 'Manual',
};

const TORBOX_PILL = { ok: 'ready', degraded: 'queued', down: 'failed' } as const;

export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: summary } = useQuery({
    queryKey: ['shell-summary'],
    queryFn: api.shellSummary,
    staleTime: 60_000,
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session, staleTime: 60_000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const title = CRUMBS[location.pathname] || 'Mycelium';

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-bg/80 backdrop-blur">
      <div className="flex items-center gap-3 px-4 py-3 lg:px-8">
        <button
          className="-ml-2 rounded p-2 text-body hover:bg-card lg:hidden"
          onClick={onOpenMenu}
          aria-label="Open menu"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>

        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted">MYCELIUM</span>
          <span className="text-muted">/</span>
          <h1 className="text-base font-semibold text-body">{title}</h1>
        </div>

        <form
          className="ml-4 hidden max-w-sm flex-1 sm:block"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
          }}
        >
          <div className="relative">
            <input
              ref={searchRef}
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search titles"
              className="w-full rounded-lg border border-border bg-card py-1.5 pl-3 pr-12 text-sm
                         text-body placeholder:text-muted focus:border-accent focus:outline-none"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-[10px] text-muted">
              ⌘K
            </span>
          </div>
        </form>

        <div className="ml-auto flex items-center gap-2">
          {summary && <Pill state={TORBOX_PILL[summary.torbox.state]}>{summary.torbox.label}</Pill>}
          {session?.user && <RegionPicker region={session.user.region || 'NL'} />}
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test -- Topbar`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/shell/
git commit -m "feat(ui): topbar with breadcrumb, TorBox pill and cmd-K search

RegionPicker moves out of Layout.tsx unchanged in behaviour, including
every query invalidation, since changing region must still refetch the
discover rows."
```

---

### Task 9: Compose the shell and retire the old Layout

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Test: `frontend/src/components/Layout.test.tsx`

**Interfaces:**
- Consumes: `Sidebar` (Task 7), `Topbar` (Task 8).
- Produces: `Layout` unchanged as the default export used by `App.tsx`, so no route changes.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/Layout.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Layout from './Layout';

vi.mock('../api', () => ({
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 1, requests: 2, wanted: 3 },
      torbox: { state: 'ok', label: 'TorBox online' },
    }),
    session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin', region: 'NL' } }),
  },
}));

describe('Layout', () => {
  it('renders the shell around the routed page', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library']}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="library" element={<p>page body</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Discover')).toBeInTheDocument();   // sidebar
    expect(screen.getByText('MYCELIUM')).toBeInTheDocument();          // topbar
    expect(screen.getByText('page body')).toBeInTheDocument();         // outlet
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Layout`
Expected: FAIL, the old Layout renders emoji navigation and no `MYCELIUM` crumb.

- [ ] **Step 3: Replace Layout**

`frontend/src/components/Layout.tsx`, entire contents:

```tsx
import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './shell/Sidebar';
import { Topbar } from './shell/Topbar';

export default function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-bg text-body">
      <Sidebar open={drawerOpen} onNavigate={() => setDrawerOpen(false)} />

      {drawerOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setDrawerOpen(true)} />
        <main className="flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

`Layout.tsx` should now be under 30 lines. Everything else it held (`TopbarSearch`, `SidebarSection`, `REGIONS`, `RegionPicker`, `Breadcrumb`, `navItems`, `adminItems`) has moved and must be deleted from this file.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test`
Expected: PASS, every suite.

- [ ] **Step 5: Check types on the files you touched**

Run: `cd frontend && npx tsc --noEmit`
Expected: only the three pre-existing errors in `PosterCard.tsx`, `usePluginSlots.ts` and `Watchlist.tsx`. No errors in `design/`, `components/primitives/`, `components/shell/` or `Layout.tsx`.

- [ ] **Step 6: Build and inspect**

Run: `cd frontend && npm run build`
Expected: success.

Run: `cd frontend && npm run dev`, open the app, and confirm by eye: near-black ground, purple active nav item, SVG icons rather than emoji, counts beside Watchlist / My Requests / Wanted, `MYCELIUM / <page>` in the topbar, a TorBox pill, and `⌘K` focusing the search field.

- [ ] **Step 7: Confirm nothing regressed server-side**

Run: `./.venv-sdd/bin/python -m pytest tests/ -q && node --test tests/js/filter_rules.test.js`
Expected: 448 passed, 34 JS passed.

- [ ] **Step 8: Commit**

```bash
git add frontend/src static/app/
git commit -m "refactor(ui): Layout becomes a thin shell composition

289 lines holding the sidebar, topbar, search, breadcrumb and region
picker inline become a 25-line composition over four focused files."
```

---

## Done when

- `npm test` passes in `frontend/`, `./.venv-sdd/bin/python -m pytest tests/ -q` reports 448, and `node --test tests/js/filter_rules.test.js` reports 34.
- No emoji remains in any navigation element.
- `grep -r "fonts.googleapis\|fonts.gstatic" frontend/src static/app/` returns nothing.
- `grep -rn "#6366f1\|22d3ee\|0d9488\|5eead4" frontend/src frontend/tailwind.config.js frontend/index.html` returns nothing. The favicon data URI counts.
- `frontend/src/components/Layout.tsx` is under 30 lines.
- `static/app/` is rebuilt and committed.

Plan 2 (the eight React screens) starts from this branch.
