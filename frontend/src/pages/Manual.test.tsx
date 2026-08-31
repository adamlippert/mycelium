import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import Manual, { CONTENT_CLASSES } from './Manual';

// A small standalone doc shaped like docs/install-guide.html: a <style> and
// two <script> tags the real page relies on for its language/JS toggles,
// plus two h2 sections to exercise ToC derivation.
const SAMPLE_HTML = `<!doctype html>
<html>
<head>
  <style>body { color: red; }</style>
</head>
<body>
  <nav><a href="#one" onclick="doSomething()">skip me</a></nav>
  <main>
    <h1>Install Guide</h1>
    <section id="one">
      <h2>First Section</h2>
      <p>First section text.</p>
    </section>
    <section id="two">
      <h2>Second Section</h2>
      <p>Second section text.</p>
      <script>window.__pwned = true;</script>
      <div class="alert danger">
        <span class="alert-icon">!</span>
        <span>Danger alert text.</span>
      </div>
      <div class="tree">
        <span class="dir">movies/</span><br>
        <span class="comment-tree">Comment tree text.</span>
      </div>
    </section>
  </main>
  <script>document.body.className = 'en';</script>
</body>
</html>`;

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(SAMPLE_HTML),
      } as Response),
    ),
  );
}

describe('Manual', () => {
  beforeEach(() => {
    stubFetch();
    (window as unknown as { __pwned?: boolean }).__pwned = undefined;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('derives ToC entries from the document\'s own headings and renders the content', async () => {
    render(<Manual />);

    await waitFor(() => expect(screen.getByText('First section text.')).toBeInTheDocument());
    expect(screen.getByText('Second section text.')).toBeInTheDocument();

    expect(screen.getByRole('button', { name: 'First Section' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Second Section' })).toBeInTheDocument();
  });

  it('never lets a <script> from the source survive in the rendered container, and never executes one', async () => {
    const { container } = render(<Manual />);

    await waitFor(() => expect(screen.getByText('First section text.')).toBeInTheDocument());

    expect(container.querySelectorAll('script').length).toBe(0);
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it('links to the README on GitHub', async () => {
    render(<Manual />);

    await waitFor(() => expect(screen.getByText('First section text.')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /README on GitHub/i });
    expect(link).toHaveAttribute('href', 'https://github.com/adamlippert/mycelium#readme');
  });

  it('drops the detached <style> and any inline event handler attributes from the source', async () => {
    const { container } = render(<Manual />);

    await waitFor(() => expect(screen.getByText('First section text.')).toBeInTheDocument());

    expect(container.querySelectorAll('style').length).toBe(0);
    // The <nav> with the onclick handler is outside <main> and is never cloned in.
    expect(container.querySelector('[onclick]')).toBeNull();
    expect(screen.queryByText('skip me')).not.toBeInTheDocument();
  });

  it('renders the danger alert and the comment-tree annotation from the source doc', async () => {
    render(<Manual />);

    await waitFor(() => expect(screen.getByText('First section text.')).toBeInTheDocument());
    expect(screen.getByText('Danger alert text.')).toBeInTheDocument();
    expect(screen.getByText('Comment tree text.')).toBeInTheDocument();
  });

  it('styles .alert.danger distinctly from a plain .alert, and .comment-tree distinctly from a plain .tree', () => {
    const classes = CONTENT_CLASSES;

    // Plain .alert and .tree get only the shared neutral treatment.
    expect(classes).toMatch(/\[&_\.alert\]:[^ ]*\bborder-border\b/);
    expect(classes).toMatch(/\[&_\.tree\]:[^ ]*\btext-muted\b/);

    // .alert.danger carries its own danger-token rule, not just the base
    // .alert rule (border-border/bg-card-raised/text-muted).
    expect(classes).toMatch(/\[&_\.alert\.danger\]:[^ ]*\btext-danger\b/);
    expect(classes).toMatch(/\[&_\.alert\.danger\]:[^ ]*\bborder-danger\b/);

    // .comment-tree carries its own rule distinct from the .tree box rule.
    expect(classes).toMatch(/\[&_\.comment-tree\]:[^ ]*\bitalic\b/);
    expect(classes).not.toMatch(/\[&_\.tree\]:[^ ]*\bitalic\b/);
  });
});
