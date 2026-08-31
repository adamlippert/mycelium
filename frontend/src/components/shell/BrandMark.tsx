/** The 32px gradient tile + network-node glyph in front of the "myc3l1um"
 * wordmark, per docs/superpowers/specs/assets/2026-08-30-ui-overhaul-mockup.html
 * (~line 33). The glyph itself is the favicon's five-circle network shape
 * (frontend/index.html's data-URI SVG), recolored for the tile's dark
 * gradient background instead of the page background it was drawn for.
 * Shared by Sidebar.tsx and Login.tsx so the two brand blocks match. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <div
      className="flex flex-none items-center justify-center rounded-[9px]"
      style={{
        width: size,
        height: size,
        background: 'linear-gradient(150deg, rgba(97,82,223,0.9), #231c6b)',
        boxShadow: '0 0 0 1px rgba(159,146,255,0.25), 0 6px 18px -8px rgba(97,82,223,0.9)',
      }}
      aria-hidden="true"
    >
      <svg width={size * 0.69} height={size * 0.69} viewBox="0 0 80 80">
        <g stroke="rgba(255,255,255,0.5)" strokeWidth="1.8" opacity="0.7" fill="none">
          <line x1="20" y1="40" x2="60" y2="20" />
          <line x1="20" y1="40" x2="60" y2="60" />
          <line x1="60" y1="20" x2="60" y2="60" />
          <line x1="40" y1="10" x2="20" y2="40" />
          <line x1="40" y1="70" x2="20" y2="40" />
          <line x1="40" y1="10" x2="60" y2="20" />
          <line x1="40" y1="70" x2="60" y2="60" />
          <line x1="40" y1="10" x2="40" y2="70" opacity="0.3" />
        </g>
        <circle cx="20" cy="40" r="5.5" fill="#ffffff" />
        <circle cx="60" cy="20" r="4.5" fill="#c7c2ff" />
        <circle cx="60" cy="60" r="4.5" fill="#c7c2ff" />
        <circle cx="40" cy="10" r="3.5" fill="#c7c2ff" />
        <circle cx="40" cy="70" r="3.5" fill="#c7c2ff" />
      </svg>
    </div>
  );
}
