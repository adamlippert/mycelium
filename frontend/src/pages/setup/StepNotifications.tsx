import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepNotifications({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Notifications</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Optional. Get pinged on successful adds, failures, deadman alerts, disk-space warnings.
      </p>
      <TextField
        id="DISCORD_WEBHOOK_URL"
        label="Discord webhook URL"
        type="password"
        value={data.DISCORD_WEBHOOK_URL}
        onChange={(v) => set('DISCORD_WEBHOOK_URL', v)}
        placeholder="optional"
      />
      <TestButton kind="discord" label="Test connection" buildFormData={() => buildFormData(data)} />
      <div className="mt-3.5">
        <TextField
          id="TELEGRAM_BOT_TOKEN"
          label="Telegram bot token"
          type="password"
          value={data.TELEGRAM_BOT_TOKEN}
          onChange={(v) => set('TELEGRAM_BOT_TOKEN', v)}
          placeholder="optional"
        />
      </div>
      <TextField
        id="TELEGRAM_CHAT_ID"
        label="Telegram chat ID"
        value={data.TELEGRAM_CHAT_ID}
        onChange={(v) => set('TELEGRAM_CHAT_ID', v)}
        placeholder="optional"
      />
      <TestButton kind="telegram" label="Test connection" buildFormData={() => buildFormData(data)} />
    </div>
  );
}
