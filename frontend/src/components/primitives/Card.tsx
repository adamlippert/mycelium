export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-card border border-border rounded-xl p-4 ${className}`.trim()}>
      {children}
    </div>
  );
}
