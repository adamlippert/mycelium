import { useCallback, useEffect, useRef, useState } from 'react';

interface TocEntry {
  id: string;
  text: string;
  level: 1 | 2;
}

const README_URL = 'https://github.com/adamlippert/mycelium#readme';

const CONTENT_CLASSES = [
  // Headings
  '[&_h1]:mb-3 [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:text-body',
  '[&_h2]:mb-4 [&_h2]:mt-10 [&_h2]:flex [&_h2]:scroll-mt-6 [&_h2]:items-center [&_h2]:gap-2 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-body',
  '[&_h3]:mb-2 [&_h3]:mt-6 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:uppercase [&_h3]:tracking-wide [&_h3]:text-muted',
  '[&_section]:mb-10 [&_section]:scroll-mt-6',
  // Body text
  '[&_p]:mb-3 [&_p]:text-sm [&_p]:leading-relaxed [&_p]:text-muted',
  '[&_strong]:font-semibold [&_strong]:text-body',
  '[&_a]:text-accent-light [&_a]:underline [&_a]:underline-offset-2 [&_a:hover]:text-accent-pale',
  '[&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:text-sm [&_ul]:text-muted',
  '[&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:text-sm [&_ol]:text-muted',
  '[&_li]:mb-1',
  '[&_hr]:my-6 [&_hr]:border-border',
  // Inline code / command blocks
  '[&_code]:rounded [&_code]:bg-card-raised [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_code]:text-accent-pale',
  '[&_.cmd]:mb-3 [&_.cmd]:overflow-x-auto [&_.cmd]:rounded-md [&_.cmd]:border [&_.cmd]:border-border [&_.cmd]:bg-card-raised [&_.cmd]:p-4 [&_.cmd]:font-mono [&_.cmd]:text-xs [&_.cmd]:leading-loose [&_.cmd]:text-accent-pale',
  '[&_.cmd_code]:bg-transparent [&_.cmd_code]:p-0',
  '[&_.tree]:mb-3 [&_.tree]:overflow-x-auto [&_.tree]:rounded-md [&_.tree]:border [&_.tree]:border-border [&_.tree]:bg-card-raised [&_.tree]:p-4 [&_.tree]:font-mono [&_.tree]:text-xs [&_.tree]:leading-loose [&_.tree]:text-muted',
  // Callouts / badges / numbered markers, reusing the source doc's own class names
  '[&_.alert]:mb-3 [&_.alert]:flex [&_.alert]:gap-2 [&_.alert]:rounded-md [&_.alert]:border [&_.alert]:border-border [&_.alert]:bg-card-raised [&_.alert]:p-3 [&_.alert]:text-sm [&_.alert]:text-muted',
  '[&_.badge]:mb-3 [&_.badge]:inline-block [&_.badge]:rounded-full [&_.badge]:border [&_.badge]:border-accent/30 [&_.badge]:bg-accent/10 [&_.badge]:px-2.5 [&_.badge]:py-1 [&_.badge]:font-mono [&_.badge]:text-xs [&_.badge]:text-accent-light',
  '[&_.section-num]:mr-2 [&_.section-num]:inline-flex [&_.section-num]:h-6 [&_.section-num]:w-6 [&_.section-num]:items-center [&_.section-num]:justify-center [&_.section-num]:rounded-full [&_.section-num]:bg-accent [&_.section-num]:text-xs [&_.section-num]:font-semibold [&_.section-num]:text-white',
  '[&_.section-opt]:mr-2 [&_.section-opt]:inline-flex [&_.section-opt]:h-6 [&_.section-opt]:w-6 [&_.section-opt]:items-center [&_.section-opt]:justify-center [&_.section-opt]:rounded-full [&_.section-opt]:border [&_.section-opt]:border-border [&_.section-opt]:bg-card-raised [&_.section-opt]:text-xs [&_.section-opt]:font-semibold [&_.section-opt]:text-muted',
  // Steps / service grid
  '[&_.step]:mb-3 [&_.step]:flex [&_.step]:gap-3 [&_.step]:text-sm [&_.step]:text-muted',
  '[&_.service-grid]:mb-3 [&_.service-grid]:grid [&_.service-grid]:grid-cols-1 [&_.service-grid]:gap-3 sm:[&_.service-grid]:grid-cols-2',
  '[&_.service-card]:rounded-lg [&_.service-card]:border [&_.service-card]:border-border [&_.service-card]:bg-card-raised [&_.service-card]:p-3 [&_.service-card]:text-sm [&_.service-card]:text-muted',
  // Tables
  '[&_table]:mb-4 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm',
  '[&_th]:border [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-body',
  '[&_td]:border [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:text-muted',
].join(' ');

/** Slugifies heading text into a stable, collision-free id. */
function slugify(text: string, seen: Set<string>): string {
  const base = text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'section';
  let id = base;
  let n = 2;
  while (seen.has(id)) {
    id = `${base}-${n++}`;
  }
  seen.add(id);
  return id;
}

/** Readable text for a heading, treating <br> as a space so "Title<br>Sub"
 * doesn't collapse into "TitleSub". */
function headingText(el: Element): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('br').forEach((br) => br.replaceWith(' '));
  return (clone.textContent ?? '').trim().replace(/\s+/g, ' ');
}

/**
 * Deep-clones the fetched document's content into a live DOM node, node by
 * node, rather than assigning a serialized string via innerHTML. This drops
 * <script>/<style> elements outright, strips on* handler attributes and
 * javascript: URLs from href/src attributes, and skips the install guide's
 * Dutch/NAS toggle variants: the source page's own script defaulted to
 * English + Proxmox on load (`setLang('en'); setPlatform('proxmox')`), and
 * since that script is stripped we bake the same default in statically
 * instead of showing both language/platform variants stacked on top of
 * each other.
 */
function sanitizeInto(source: Element, target: Node) {
  for (const child of Array.from(source.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      target.appendChild(document.createTextNode(child.textContent ?? ''));
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue;
    const el = child as Element;
    const tag = el.tagName.toLowerCase();
    if (tag === 'script' || tag === 'style') continue;
    if (el.classList.contains('lang-nl') || el.classList.contains('plat-nas')) continue;

    const clone = document.createElement(tag);
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith('on')) continue;
      if ((name === 'href' || name === 'src') && /^\s*javascript:/i.test(attr.value)) continue;
      clone.setAttribute(attr.name, attr.value);
    }
    sanitizeInto(el, clone);
    target.appendChild(clone);
  }
}

/** Native replacement for the old /manual iframe: fetches the standalone
 * install guide, strips its script/style, restyles the content with the
 * app's own typography, and derives a scroll-spying table of contents from
 * the document's own h1/h2 headings. */
export default function Manual() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [toc, setToc] = useState<TocEntry[]>([]);
  const [activeId, setActiveId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch('/docs/install-guide.html')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((html) => {
        if (cancelled) return;
        const container = containerRef.current;
        if (!container) return;

        const parsed = new DOMParser().parseFromString(html, 'text/html');
        const source = parsed.querySelector('main') ?? parsed.body;

        container.replaceChildren();
        sanitizeInto(source, container);

        const seen = new Set<string>();
        const entries: TocEntry[] = [];
        container.querySelectorAll('h1, h2').forEach((h) => {
          const text = headingText(h);
          if (!text) return;
          const id = slugify(text, seen);
          h.id = id;
          entries.push({ id, text, level: h.tagName === 'H1' ? 1 : 2 });
        });
        setToc(entries);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load manual');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // jsdom (our test environment) has no IntersectionObserver; guard rather
  // than polyfill so the component degrades to "no scroll-spy" instead of
  // throwing outside a real browser.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const container = containerRef.current;
    if (!container || toc.length === 0) return;

    const headings = toc
      .map((entry) => container.querySelector(`#${CSS.escape(entry.id)}`))
      .filter((el): el is Element => el !== null);
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (observed) => {
        const visible = observed.filter((entry) => entry.isIntersecting);
        if (visible.length === 0) return;
        const topmost = visible.reduce((a, b) =>
          a.boundingClientRect.top <= b.boundingClientRect.top ? a : b,
        );
        setActiveId(topmost.target.id);
      },
      { rootMargin: '0px 0px -70% 0px', threshold: 0 },
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [toc]);

  const scrollToHeading = useCallback((id: string) => {
    const el = containerRef.current?.querySelector(`#${CSS.escape(id)}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  return (
    <div className="flex gap-8">
      <aside className="hidden w-56 shrink-0 lg:block">
        <div className="sticky top-6 space-y-4">
          <a
            href={README_URL}
            target="_blank"
            rel="noreferrer"
            className="block text-xs font-semibold text-accent-light hover:text-accent-pale"
          >
            README on GitHub &rarr;
          </a>
          {toc.length > 0 && (
            <nav aria-label="Manual contents" className="space-y-0.5 text-sm">
              {toc.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => scrollToHeading(entry.id)}
                  className={`block w-full truncate rounded px-2 py-1 text-left transition-colors ${
                    entry.level === 1 ? 'font-semibold' : 'pl-4 text-[13px]'
                  } ${
                    activeId === entry.id
                      ? 'bg-accent/10 text-accent-light'
                      : 'text-muted hover:text-body'
                  }`}
                >
                  {entry.text}
                </button>
              ))}
            </nav>
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1 pb-16">
        {loading && <p className="text-sm text-muted">Loading manual...</p>}
        {error && (
          <p className="text-sm text-danger">Could not load the manual ({error}).</p>
        )}
        <div ref={containerRef} className={CONTENT_CLASSES} />
      </div>
    </div>
  );
}
