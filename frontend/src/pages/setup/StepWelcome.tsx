import type { SetField, SetupData } from './types';

export default function StepWelcome({ data, set }: { data: SetupData; set: SetField }) {
  const lite = data.LITE_MODE;
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Welcome.</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Mycelium turns Seerr requests into Jellyfin-ready streams via TorBox in about 30 seconds.
        First, choose how you want to deploy it.
      </p>

      <div className="mb-4 grid grid-cols-2 gap-2.5">
        <label
          onClick={() => set('LITE_MODE', false)}
          className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border-2 p-3.5 ${
            lite ? 'border-border bg-transparent' : 'border-accent bg-accent/[0.07]'
          }`}
        >
          <div className="flex items-center gap-2">
            <input type="radio" name="_wz_mode" value="full" checked={!lite} readOnly className="accent-accent" />
            <span className="text-[13px] font-bold text-body">Full</span>
          </div>
          <span className="text-[11px] leading-relaxed text-muted">
            React SPA + auto-scheduler + webplayer + trakt.
            <br />
            For users who browse and discover via the Mycelium interface.
          </span>
        </label>
        <label
          onClick={() => set('LITE_MODE', true)}
          className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border-2 p-3.5 ${
            lite ? 'border-accent bg-accent/[0.07]' : 'border-border bg-transparent'
          }`}
        >
          <div className="flex items-center gap-2">
            <input type="radio" name="_wz_mode" value="lite" checked={lite} readOnly className="accent-accent" />
            <span className="text-[13px] font-bold text-body">Lite</span>
          </div>
          <span className="text-[11px] leading-relaxed text-muted">
            Webhook + processor + /admin only. No SPA schedulers, no plugins.
            <br />
            For Seerr/Jellyfin-only setups where the SPA is not used.
          </span>
        </label>
      </div>

      <div className="rounded-md border-l-[3px] border-accent bg-accent/[0.08] px-3.5 py-2.5 text-[12px] text-accent">
        If you&apos;d rather edit{' '}
        <code className="rounded bg-card-raised px-1.5 py-px font-mono text-[12px] text-accent">.env</code>{' '}
        directly, click <b>Skip wizard</b> at the bottom.
      </div>
    </div>
  );
}
