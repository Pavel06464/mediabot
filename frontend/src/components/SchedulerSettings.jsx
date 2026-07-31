import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { CalendarClock, Trash2, ArrowUp, ArrowDown, Image as ImageIcon, Film, Plus, Send, Radio } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";

const PRESETS = [
  { m: 30, label: "30 мин" },
  { m: 60, label: "1 час" },
  { m: 180, label: "3 часа" },
  { m: 360, label: "6 часов" },
  { m: 1440, label: "Сутки" },
];

const fmtUTC = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU", { timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) + " UTC";
  } catch { return iso; }
};

const fromMinutes = (m) => ({ d: Math.floor(m / 1440), h: Math.floor((m % 1440) / 60), m: m % 60 });

export default function SchedulerSettings({ open, onOpenChange, onChange }) {
  const [channels, setChannels] = useState([]);
  const [selId, setSelId] = useState(null);
  const [queue, setQueue] = useState([]);
  const [newChan, setNewChan] = useState("");
  const [adding, setAdding] = useState(false);
  const [iv, setIv] = useState({ d: 0, h: 1, m: 0 });

  const sel = channels.find((c) => c.id === selId) || null;

  const loadChannels = useCallback(async () => {
    try {
      const { data } = await api.get("/channels");
      setChannels(data.channels || []);
      setSelId((prev) => (prev && data.channels.some((c) => c.id === prev) ? prev : (data.channels[0]?.id || null)));
    } catch { /* ignore */ }
  }, []);

  const loadQueue = useCallback(async (id) => {
    if (!id) { setQueue([]); return; }
    try {
      const { data } = await api.get(`/channels/${id}/queue`);
      setQueue(data.queue || []);
    } catch { setQueue([]); }
  }, []);

  useEffect(() => { if (open) loadChannels(); }, [open, loadChannels]);
  useEffect(() => {
    if (selId) {
      loadQueue(selId);
      const c = channels.find((x) => x.id === selId);
      if (c) setIv(fromMinutes(c.interval_minutes));
    }
  }, [selId, channels, loadQueue]);

  const addChannel = async () => {
    if (!newChan.trim()) return;
    setAdding(true);
    try {
      const { data } = await api.post("/channels", { identifier: newChan.trim() });
      toast.success(`Канал «${data.channel_title}» добавлен`);
      setNewChan("");
      await loadChannels();
      setSelId(data.id);
      onChange?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Не удалось добавить канал");
    } finally {
      setAdding(false);
    }
  };

  const saveChannel = async (patch) => {
    if (!sel) return;
    const body = {
      enabled: patch.enabled ?? sel.enabled,
      interval_minutes: patch.interval_minutes ?? sel.interval_minutes,
      auto_enqueue: patch.auto_enqueue ?? sel.auto_enqueue,
    };
    try {
      await api.put(`/channels/${sel.id}`, body);
      await loadChannels();
      onChange?.();
    } catch { toast.error("Не удалось сохранить"); }
  };

  const applyInterval = () => {
    const total = (iv.d || 0) * 1440 + (iv.h || 0) * 60 + (iv.m || 0);
    if (total < 1) return toast.error("Интервал должен быть не меньше 1 минуты");
    saveChannel({ interval_minutes: total });
    toast.success("Интервал сохранён");
  };

  const removeChannel = async () => {
    if (!sel || !window.confirm(`Удалить канал «${sel.channel_title}»?`)) return;
    try {
      await api.delete(`/channels/${sel.id}`);
      toast.success("Канал удалён");
      await loadChannels();
      onChange?.();
    } catch { toast.error("Ошибка"); }
  };

  const publishAll = async () => {
    if (!sel || !window.confirm(`Опубликовать все готовые посты канала «${sel.channel_title}» по одному с паузой 5 c?`)) return;
    try {
      const { data } = await api.post(`/channels/${sel.id}/publish-all`);
      toast.success(`Публикуется ${data.started} постов`);
      loadQueue(sel.id);
      onChange?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Ошибка"); }
  };

  const removeFromQueue = async (id) => {
    try { await api.post(`/posts/${id}/queue`, { in_queue: false }); loadQueue(sel.id); loadChannels(); onChange?.(); }
    catch { toast.error("Ошибка"); }
  };

  const move = async (idx, dir) => {
    const j = idx + dir;
    if (j < 0 || j >= queue.length) return;
    const next = [...queue];
    [next[idx], next[j]] = [next[j], next[idx]];
    setQueue(next);
    try { await api.put(`/channels/${sel.id}/queue`, { order: next.map((x) => x.id) }); onChange?.(); }
    catch { toast.error("Не удалось изменить порядок"); loadQueue(sel.id); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none sm:max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="scheduler-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5 text-[#0055FF]" /> Каналы и планировщик
          </DialogTitle>
          <DialogDescription>Управляйте каналами и настраивайте свой план публикаций для каждого. Время — по UTC.</DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2 border border-zinc-200 p-3">
          <input
            value={newChan}
            onChange={(e) => setNewChan(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addChannel()}
            placeholder="@username или -100… канала (бот должен быть админом)"
            className="flex-1 border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF]"
            data-testid="add-channel-input"
          />
          <Button onClick={addChannel} disabled={adding} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="add-channel-btn">
            <Plus className="h-4 w-4 mr-1" /> {adding ? "Добавляю…" : "Добавить"}
          </Button>
        </div>

        {channels.length === 0 ? (
          <div className="text-sm text-zinc-400 border border-dashed border-zinc-200 p-6 text-center" data-testid="no-channels">
            Пока нет каналов. Добавьте первый выше.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-[220px_1fr] gap-4">
            <div className="space-y-1.5" data-testid="channel-list">
              {channels.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelId(c.id)}
                  className={`w-full text-left border p-3 transition-colors duration-150 ${selId === c.id ? "border-[#0055FF] bg-blue-50" : "border-zinc-200 hover:border-zinc-300"}`}
                  data-testid={`channel-tab-${c.id}`}
                >
                  <div className="flex items-center gap-2">
                    <Radio className={`h-3.5 w-3.5 ${c.enabled ? "text-green-600" : "text-zinc-300"}`} />
                    <span className="font-semibold text-sm truncate">{c.channel_title}</span>
                  </div>
                  <div className="text-xs text-zinc-400 mt-1">Очередь: {c.queue_count} · {c.enabled ? "авто вкл" : "авто выкл"}</div>
                </button>
              ))}
            </div>

            {sel && (
              <div className="space-y-4" data-testid="channel-panel">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-bold">{sel.channel_title}</div>
                    <div className="text-xs text-zinc-400">{sel.channel_username ? `@${sel.channel_username}` : sel.channel_id}</div>
                  </div>
                  <button onClick={removeChannel} className="text-zinc-400 hover:text-[#FF3333] p-2" title="Удалить канал" data-testid="delete-channel-btn">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                <div className="flex items-center justify-between border border-zinc-200 p-3">
                  <div>
                    <div className="font-semibold text-sm">Авто-публикация из очереди</div>
                    <div className="text-xs text-zinc-400 mt-0.5">{sel.enabled ? `Следующая: ${fmtUTC(sel.next_run_at)}` : "Выключена"}</div>
                  </div>
                  <Switch checked={sel.enabled} onCheckedChange={(v) => saveChannel({ enabled: v })} data-testid="channel-enabled-toggle" />
                </div>

                <div className="border border-zinc-200 p-3 space-y-2">
                  <div className="label-caps text-zinc-500">Интервал публикации</div>
                  <div className="flex items-end gap-2">
                    {[["d", "дни"], ["h", "часы"], ["m", "мин"]].map(([k, lbl]) => (
                      <div key={k} className="flex flex-col">
                        <label className="text-xs text-zinc-400 mb-1">{lbl}</label>
                        <input type="number" min="0" value={iv[k]}
                          onChange={(e) => setIv((p) => ({ ...p, [k]: Math.max(0, parseInt(e.target.value || "0", 10)) }))}
                          className="w-16 border border-zinc-200 px-2 py-1.5 text-sm outline-none focus:border-[#0055FF]"
                          data-testid={`interval-${k}`} />
                      </div>
                    ))}
                    <Button onClick={applyInterval} variant="outline" className="rounded-none border-[#0055FF] text-[#0055FF] h-9" data-testid="interval-apply">Сохранить</Button>
                  </div>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {PRESETS.map((p) => (
                      <button key={p.m} onClick={() => { setIv(fromMinutes(p.m)); saveChannel({ interval_minutes: p.m }); toast.success("Интервал сохранён"); }}
                        className="text-xs border border-zinc-200 px-2 py-1 hover:border-[#0055FF] hover:text-[#0055FF]" data-testid={`preset-${p.m}`}>
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between border border-zinc-200 p-3">
                  <div>
                    <div className="font-semibold text-sm">Авто-постановка в очередь</div>
                    <div className="text-xs text-zinc-400 mt-0.5">Новые посты этого канала сами попадают в очередь</div>
                  </div>
                  <Switch checked={sel.auto_enqueue} onCheckedChange={(v) => saveChannel({ auto_enqueue: v })} data-testid="channel-autoenqueue-toggle" />
                </div>

                <Button onClick={publishAll} variant="outline" className="rounded-none border-[#0055FF] text-[#0055FF] w-full" data-testid="channel-publish-all">
                  <Send className="h-4 w-4 mr-2" /> Опубликовать все в этот канал
                </Button>

                <div>
                  <div className="label-caps text-zinc-500 mb-2">Очередь ({queue.length})</div>
                  {queue.length === 0 ? (
                    <div className="text-sm text-zinc-400 border border-dashed border-zinc-200 p-4 text-center" data-testid="queue-empty">Очередь пуста</div>
                  ) : (
                    <div className="space-y-2 max-h-56 overflow-y-auto" data-testid="queue-list">
                      {queue.map((p, idx) => (
                        <div key={p.id} className="flex items-center gap-3 border border-zinc-200 p-2" data-testid={`queue-item-${p.id}`}>
                          <span className="text-xs font-bold text-zinc-400 w-5 text-center">{idx + 1}</span>
                          {p.cover_url ? <img src={p.cover_url} alt="" className="h-9 w-9 object-cover border border-zinc-200" /> : <div className="h-9 w-9 bg-zinc-900 flex items-center justify-center"><Film className="h-4 w-4 text-white" /></div>}
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold truncate">{p.title}</div>
                            <div className="text-xs text-zinc-400 flex items-center gap-2">
                              <span className="flex items-center gap-0.5"><ImageIcon className="h-3 w-3" />{p.photo_count ?? 0}</span>
                              <span className="flex items-center gap-0.5"><Film className="h-3 w-3" />{p.video_count ?? 0}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-0.5">
                            <button onClick={() => move(idx, -1)} disabled={idx === 0} className="p-1 text-zinc-400 hover:text-[#0055FF] disabled:opacity-30" data-testid={`queue-up-${p.id}`}><ArrowUp className="h-4 w-4" /></button>
                            <button onClick={() => move(idx, 1)} disabled={idx === queue.length - 1} className="p-1 text-zinc-400 hover:text-[#0055FF] disabled:opacity-30" data-testid={`queue-down-${p.id}`}><ArrowDown className="h-4 w-4" /></button>
                            <button onClick={() => removeFromQueue(p.id)} className="p-1 text-zinc-400 hover:text-[#FF3333]" data-testid={`queue-remove-${p.id}`}><Trash2 className="h-4 w-4" /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
