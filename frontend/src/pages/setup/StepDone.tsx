export default function StepDone() {
  const webhookUrl = `${window.location.origin}/webhook`;
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">All set.</h2>
      <p className="mb-4 text-[13px] leading-relaxed text-muted">
        Mycelium will save your settings and take you to the dashboard. Configure Seerr&apos;s
        notifications webhook to point at:
      </p>
      <div className="mb-4 rounded-md border-l-[3px] border-ok bg-ok/[0.08] px-3.5 py-2.5 font-mono text-[12px] text-ok">
        {webhookUrl}
      </div>
      <p className="text-[13px] leading-relaxed text-muted">
        Anything you skipped can be added anytime under <b>Settings &rarr; Connections</b>.
      </p>
    </div>
  );
}
