import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { CalendarClock, Trash2, ArrowUp, ArrowDown, Image as ImageIcon, Film, Clock } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import api from "@/lib/api";

const INTERVALS = [
  { v: 30, label: "Каждые 30 минут" },
  { v: 60, label: "Каждый час" },
  { v: 180, label: "Каждые 3 часа" },
  { v: 360, label: "Каждые 6 часов" },
  { v: 1440, label: "Раз в сутки" },
];

const fmtUTC = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    }) + " UTC";
  } catch { return iso; }
};

export default function SchedulerSettings({ open, onOpenChange, onChange }) {
  const [cfg, setCfg] = useState({ enabled: false, interval_minutes: 60, next_run_at: null });
  const [queue, setQueue] = useState([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/settings/scheduler");
      setCfg({ enabled: data.enabled, interval_minutes: data.interval_minutes, next_run_at: data.next_run_at });
      setQueue(data.queue || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { if (open) load(); }, [open, load]);

  const persist = async (next) => {
    setSaving(true);
    try {
      const { data } = await api.put("/settings/scheduler", { enabled: next.enabled, interval_minutes: next.interval_minutes });
      setCfg({ enabled: data.enabled, interval_minutes: data.interval_minutes, next_run_at: data.next_run_at });
      onChange?.();
    } catch {
      toast.error("Не удалось сохранить настройки");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = (v) => persist({ enabled: v, interval_minutes: cfg.interval_minutes });
  const changeInterval = (v) => persist({ enabled: cfg.enabled, interval_minutes: Number(v) });

  const removeFromQueue = async (id) => {
    try {
      await api.post(`/posts/${id}/queue`, { in_queue: false });
      setQueue((q) => q.filter((x) => x.id !== id));
      load();
      onChange?.();
    } catch { toast.error("Ошибка"); }
  };

  const move = async (idx, dir) => {
    const j = idx + dir;
    if (j < 0 || j >= queue.length) return;
    const next = [...queue];
    [next[idx], next[j]] = [next[j], next[idx]];
    setQueue(next);
    try {
      await api.put("/settings/scheduler/queue", { order: next.map((x) => x.id) });
      onChange?.();
    } catch { toast.error("Не удалось изменить порядок"); load(); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none sm:max-w-lg" data-testid="scheduler-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5 text-[#0055FF]" /> Планировщик публикаций
          </DialogTitle>
          <DialogDescription>
            Авто-публикация постов из очереди с заданным интервалом. Время — по UTC.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="flex items-center justify-between border border-zinc-200 p-4">
            <div>
              <div className="font-semibold text-sm">Авто-публикация из очереди</div>
              <div className="text-xs text-zinc-400 mt-0.5">
                {cfg.enabled ? `Следующая: ${fmtUTC(cfg.next_run_at)}` : "Выключена"}
              </div>
            </div>
            <Switch checked={cfg.enabled} onCheckedChange={toggleEnabled} disabled={saving} data-testid="scheduler-toggle" />
          </div>

          <div>
            <label className="label-caps text-zinc-500 block mb-2">Интервал</label>
            <select
              value={cfg.interval_minutes}
              onChange={(e) => changeInterval(e.target.value)}
              disabled={saving}
              className="w-full border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF] bg-white"
              data-testid="scheduler-interval"
            >
              {INTERVALS.map((i) => <option key={i.v} value={i.v}>{i.label}</option>)}
            </select>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="label-caps text-zinc-500">Очередь ({queue.length})</label>
            </div>
            {queue.length === 0 ? (
              <div className="text-sm text-zinc-400 border border-dashed border-zinc-200 p-4 text-center" data-testid="queue-empty">
                Очередь пуста. Добавьте посты кнопкой «В очередь» в таблице.
              </div>
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto" data-testid="queue-list">
                {queue.map((p, idx) => (
                  <div key={p.id} className="flex items-center gap-3 border border-zinc-200 p-2" data-testid={`queue-item-${p.id}`}>
                    <span className="text-xs font-bold text-zinc-400 w-5 text-center">{idx + 1}</span>
                    {p.cover_url
                      ? <img src={p.cover_url} alt="" className="h-9 w-9 object-cover border border-zinc-200" />
                      : <div className="h-9 w-9 bg-zinc-900 flex items-center justify-center"><Film className="h-4 w-4 text-white" /></div>}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold truncate">{p.title}</div>
                      <div className="text-xs text-zinc-400 flex items-center gap-2">
                        <span className="flex items-center gap-0.5"><ImageIcon className="h-3 w-3" />{p.photo_count ?? 0}</span>
                        <span className="flex items-center gap-0.5"><Film className="h-3 w-3" />{p.video_count ?? 0}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5">
                      <button onClick={() => move(idx, -1)} disabled={idx === 0} className="p-1 text-zinc-400 hover:text-[#0055FF] disabled:opacity-30" data-testid={`queue-up-${p.id}`}>
                        <ArrowUp className="h-4 w-4" />
                      </button>
                      <button onClick={() => move(idx, 1)} disabled={idx === queue.length - 1} className="p-1 text-zinc-400 hover:text-[#0055FF] disabled:opacity-30" data-testid={`queue-down-${p.id}`}>
                        <ArrowDown className="h-4 w-4" />
                      </button>
                      <button onClick={() => removeFromQueue(p.id)} className="p-1 text-zinc-400 hover:text-[#FF3333]" data-testid={`queue-remove-${p.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <p className="text-xs text-zinc-400 flex items-start gap-1.5">
            <Clock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            Публикуется один пост за интервал, в порядке очереди. Нужен настроенный канал.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
