import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  Plus,
  FileText,
  Radio,
  Image as ImageIcon,
  Film,
  ExternalLink,
  Copy,
  Trash2,
  RefreshCw,
  Bot,
  Send,
  Settings,
  LogOut,
  Layers,
  Droplets,
  UploadCloud,
  Pencil,
  ChevronLeft,
  ChevronRight,
  Search,
  AlertTriangle,
  CalendarClock,
  Clock,
  ListPlus,
  ArrowUpDown,
  Replace,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useUpload } from "@/context/UploadContext";
import ChannelSettings from "@/components/ChannelSettings";
import WatermarkSettings from "@/components/WatermarkSettings";
import SchedulerSettings from "@/components/SchedulerSettings";

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
};

const fmtUTC = (iso) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    }) + " UTC";
  } catch { return iso; }
};

const STATUS_META = {
  uploading: { label: "ЗАГРУЗКА", cls: "border-[#0055FF] text-[#0055FF]" },
  processing: { label: "СОЗДАЁТСЯ", cls: "border-amber-400 text-amber-600" },
  ready: { label: "ГОТОВ", cls: "border-zinc-300 text-zinc-500" },
  published: { label: "В КАНАЛЕ", cls: "bg-[#00CC66] text-white border-transparent" },
  failed: { label: "ОШИБКА", cls: "border-[#FF3333] text-[#FF3333]" },
};

const jobPct = (j) => {
  if (j.status === "processing" || j.status === "done") return 100;
  if (!j.total) return 0;
  return Math.min(100, Math.round(((j.done + (j.pct || 0) / 100) / j.total) * 100));
};
const jobLabel = (j) =>
  j.status === "failed" ? "Ошибка"
    : j.status === "done" ? "Готово"
    : j.status === "processing" ? "Оформляю статью…"
    : j.attempt > 1 ? `Загрузка… (попытка ${j.attempt})`
    : "Загрузка…";

function StatCard({ label, value, icon: Icon, accent, testid, sub }) {
  return (
    <div data-testid={testid} className="bg-white border border-zinc-200 p-6 flex flex-col justify-between hover:border-zinc-400 transition-colors duration-150">
      <div className="flex items-center justify-between">
        <span className="label-caps text-zinc-500">{label}</span>
        <Icon className="h-4 w-4 text-zinc-400" strokeWidth={2} />
      </div>
      <div className="mt-6 text-5xl font-black tracking-tighter" style={{ color: accent || "#09090B" }}>{value}</div>
      {sub && <div className="mt-2 text-xs font-semibold text-[#0055FF] flex items-center gap-1" data-testid={`${testid}-sub`}>{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { jobs, retryJob, dismissJob } = useUpload();
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(null);
  const [channelOpen, setChannelOpen] = useState(false);
  const [watermarkOpen, setWatermarkOpen] = useState(false);
  const [schedulerOpen, setSchedulerOpen] = useState(false);
  const [scheduleTarget, setScheduleTarget] = useState(null);
  const [scheduleValue, setScheduleValue] = useState("");
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleChannel, setScheduleChannel] = useState("");
  const [channels, setChannels] = useState([]);
  const [channelsLoaded, setChannelsLoaded] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState(localStorage.getItem("selected_channel") || "");

  const loadChannels = useCallback(() => {
    api.get("/channels").then(({ data }) => {
      const list = data.channels || [];
      setChannels(list);
      setChannelsLoaded(true);
      setSelectedChannel((cur) => (list.some((c) => c.id === cur) ? cur : (list.length === 1 ? list[0].id : "")));
    }).catch(() => setChannelsLoaded(true));
  }, []);

  useEffect(() => { loadChannels(); }, [loadChannels, schedulerOpen]);
  useEffect(() => {
    if (selectedChannel) localStorage.setItem("selected_channel", selectedChannel);
    else localStorage.removeItem("selected_channel");
  }, [selectedChannel]);

  const chanName = (ref) => channels.find((c) => c.id === ref)?.channel_title;
  const currentChannel = channels.find((c) => c.id === selectedChannel);
  const queueEndsAt = (() => {
    if (!currentChannel?.enabled || !currentChannel?.next_run_at || !stats?.in_queue) return null;
    const base = new Date(currentChannel.next_run_at).getTime();
    if (Number.isNaN(base)) return null;
    return new Date(base + (stats.in_queue - 1) * (currentChannel.interval_minutes || 0) * 60000).toISOString();
  })();
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("date");
  const [sortDir, setSortDir] = useState("desc");
  const [publishingAll, setPublishingAll] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [delChannel, setDelChannel] = useState(false);
  const [delMedia, setDelMedia] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkFind, setBulkFind] = useState("");
  const [bulkReplace, setBulkReplace] = useState("");
  const [bulkOnlyChannel, setBulkOnlyChannel] = useState(true);
  const [bulkRunning, setBulkRunning] = useState(false);

  const runBulkReplace = async () => {
    if (!bulkFind.trim()) return toast.error("Укажите текст, который нужно заменить");
    setBulkRunning(true);
    try {
      const { data } = await api.post("/posts/bulk-replace-description", {
        find: bulkFind,
        replace: bulkReplace,
        channel_ref: bulkOnlyChannel ? selectedChannel : null,
        update_live: true,
      });
      if (data.matched === 0) {
        toast.info("Постов с таким текстом не найдено");
      } else {
        toast.success(`Замена запущена в ${data.matched} постах — идёт в фоне, обновите через минуту`);
        setBulkOpen(false);
        setBulkFind(""); setBulkReplace("");
        setTimeout(load, 3000);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Ошибка массовой замены");
    } finally {
      setBulkRunning(false);
    }
  };

  const load = useCallback(async () => {
    if (!selectedChannel) { setLoading(false); return; }
    try {
      const [s, p] = await Promise.all([
        api.get(`/stats?channel_ref=${selectedChannel}`),
        api.get(`/posts?page=${page}&page_size=20&q=${encodeURIComponent(q)}&sort_by=${sortBy}&sort_dir=${sortDir}&channel_ref=${selectedChannel}`),
      ]);
      setStats(s.data);
      setPosts(p.data.items);
      setTotalPages(p.data.pages);
    } catch (e) {
      // 401 handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [page, q, sortBy, sortDir, selectedChannel]);

  useEffect(() => {
    const t = setTimeout(() => { setQ(qInput); setPage(1); }, 400);
    return () => clearTimeout(t);
  }, [qInput]);

  useEffect(() => { load(); }, [load]);

  // Пока идут фоновые загрузки — обновляем таблицу, чтобы видеть смену статусов
  useEffect(() => {
    if (jobs.length === 0) { load(); return; }
    const iv = setInterval(load, 2500);
    return () => clearInterval(iv);
  }, [jobs.length, load]);

  const copyLink = (url) => { navigator.clipboard.writeText(url); toast.success("Ссылка скопирована"); };

  const publish = async (id) => {
    if (!channels.length) { toast.error("Сначала добавьте канал"); setSchedulerOpen(true); return; }
    setPublishing(id);
    try {
      const { data } = await api.post(`/posts/${id}/publish`);
      toast.success(`Опубликовано в «${data.channel_title}»`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Ошибка публикации");
    } finally {
      setPublishing(null);
    }
  };

  const doPublishAll = async () => {
    setConfirmAll(false);
    if (!selectedChannel) { toast.error("Сначала выберите канал"); return; }
    setPublishingAll(true);
    try {
      const { data } = await api.post(`/channels/${selectedChannel}/publish-all`);
      toast.success(`Публикуется ${data.started} постов — по одному раз в 5 секунд`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Ошибка массовой публикации");
    } finally {
      setPublishingAll(false);
    }
  };

  const removePost = (post) => {
    setDeleteTarget(post);
    setDelChannel(false);
    setDelMedia(true);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/posts/${deleteTarget.id}?delete_channel=${delChannel}&delete_media=${delMedia}`);
      toast.success("Пост удалён");
      setDeleteTarget(null);
      load();
    } catch {
      toast.error("Ошибка удаления");
    } finally {
      setDeleting(false);
    }
  };

  const openSchedule = (post) => {
    setScheduleTarget(post);
    setScheduleChannel(post.channel_ref || channels[0]?.id || "");
    if (post.scheduled_at) {
      try {
        const d = new Date(post.scheduled_at);
        const pad = (n) => String(n).padStart(2, "0");
        setScheduleValue(`${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`);
      } catch { setScheduleValue(""); }
    } else {
      setScheduleValue("");
    }
  };

  const saveSchedule = async () => {
    if (!scheduleTarget) return;
    if (!scheduleValue) return toast.error("Укажите дату и время");
    setScheduleSaving(true);
    try {
      await api.post(`/posts/${scheduleTarget.id}/schedule`, { scheduled_at: scheduleValue, channel_ref: scheduleChannel || null });
      toast.success("Пост запланирован");
      setScheduleTarget(null);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Ошибка планирования");
    } finally {
      setScheduleSaving(false);
    }
  };

  const clearSchedule = async () => {
    if (!scheduleTarget) return;
    setScheduleSaving(true);
    try {
      await api.post(`/posts/${scheduleTarget.id}/schedule`, { scheduled_at: null });
      toast.success("Расписание снято");
      setScheduleTarget(null);
      load();
    } catch {
      toast.error("Ошибка");
    } finally {
      setScheduleSaving(false);
    }
  };

  const toggleQueue = async (post) => {
    try {
      const next = !post.in_queue;
      await api.post(`/posts/${post.id}/queue`, { in_queue: next });
      toast.success(next ? "Добавлено в очередь" : "Убрано из очереди");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Ошибка");
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <ChannelSettings open={channelOpen} onOpenChange={setChannelOpen} onChange={load} />
      <WatermarkSettings open={watermarkOpen} onOpenChange={setWatermarkOpen} />
      <SchedulerSettings open={schedulerOpen} onOpenChange={setSchedulerOpen} onChange={load} />

      <Dialog open={bulkOpen} onOpenChange={(o) => !o && setBulkOpen(false)}>
        <DialogContent className="rounded-none sm:max-w-md" data-testid="bulk-replace-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Replace className="h-5 w-5 text-[#0055FF]" /> Заменить текст в описаниях
            </DialogTitle>
            <DialogDescription>
              Найдёт текст во всех описаниях и заменит его. Например, старую ссылку на новую. Опубликованные посты тоже обновятся в канале.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="label-caps text-zinc-500 block mb-1">Что заменить</label>
              <Input value={bulkFind} onChange={(e) => setBulkFind(e.target.value)} placeholder="https://old-link.com/…" className="rounded-none" data-testid="bulk-find-input" />
            </div>
            <div>
              <label className="label-caps text-zinc-500 block mb-1">На что</label>
              <Input value={bulkReplace} onChange={(e) => setBulkReplace(e.target.value)} placeholder="https://new-link.com/… (пусто = удалить)" className="rounded-none" data-testid="bulk-replace-input" />
            </div>
            <label className="flex items-start gap-3 cursor-pointer">
              <Checkbox checked={bulkOnlyChannel} onCheckedChange={(v) => setBulkOnlyChannel(!!v)} data-testid="bulk-only-channel" />
              <span className="text-sm">
                Только текущий канал {currentChannel?.channel_title ? `(${currentChannel.channel_title})` : ""}
                <span className="block text-xs text-zinc-400">Снимите галочку, чтобы заменить во всех каналах</span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkOpen(false)} className="rounded-none border-zinc-200" data-testid="bulk-cancel">Отмена</Button>
            <Button onClick={runBulkReplace} disabled={bulkRunning} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="bulk-run">
              {bulkRunning ? "Запускаю…" : "Заменить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!scheduleTarget} onOpenChange={(o) => !o && setScheduleTarget(null)}>
        <DialogContent className="rounded-none sm:max-w-md" data-testid="schedule-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CalendarClock className="h-5 w-5 text-[#0055FF]" /> Отложенная публикация
            </DialogTitle>
            <DialogDescription>
              «{scheduleTarget?.title}» уйдёт в канал в указанное время (по UTC).
            </DialogDescription>
          </DialogHeader>
          <div className="py-2 space-y-3">
            {channels.length > 0 && (
              <div>
                <label className="label-caps text-zinc-500 block mb-1">Канал</label>
                <select
                  value={scheduleChannel}
                  onChange={(e) => setScheduleChannel(e.target.value)}
                  className="w-full border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF] bg-white"
                  data-testid="schedule-channel"
                >
                  {channels.map((c) => <option key={c.id} value={c.id}>{c.channel_title}</option>)}
                </select>
              </div>
            )}
            <label className="label-caps text-zinc-500 block">Дата и время (UTC)</label>
            <input
              type="datetime-local"
              value={scheduleValue}
              onChange={(e) => setScheduleValue(e.target.value)}
              className="w-full border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF]"
              data-testid="schedule-input"
            />
            {scheduleTarget?.scheduled_at && (
              <p className="text-xs text-zinc-400">Сейчас запланировано на {fmtUTC(scheduleTarget.scheduled_at)}</p>
            )}
          </div>
          <DialogFooter className="gap-2">
            {scheduleTarget?.scheduled_at && (
              <Button variant="outline" onClick={clearSchedule} disabled={scheduleSaving} className="rounded-none border-zinc-200 mr-auto" data-testid="schedule-clear">
                Снять расписание
              </Button>
            )}
            <Button variant="outline" onClick={() => setScheduleTarget(null)} className="rounded-none border-zinc-200" data-testid="schedule-cancel">Отмена</Button>
            <Button onClick={saveSchedule} disabled={scheduleSaving} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="schedule-save">
              {scheduleSaving ? "Сохраняю…" : "Запланировать"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent className="rounded-none sm:max-w-md" data-testid="delete-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-[#FF3333]" /> Удалить пост?
            </DialogTitle>
            <DialogDescription>
              «{deleteTarget?.title}» будет удалён из панели. Выберите, что ещё удалить.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <label className="flex items-start gap-3 cursor-pointer">
              <Checkbox checked={delChannel} onCheckedChange={(v) => setDelChannel(!!v)} data-testid="del-channel-checkbox" disabled={!deleteTarget?.channel_message_id} />
              <span className="text-sm">
                Удалить сообщение в канале
                {!deleteTarget?.channel_message_id && <span className="block text-xs text-zinc-400">(этот пост не публиковался — нечего удалять)</span>}
              </span>
            </label>
            <label className="flex items-start gap-3 cursor-pointer">
              <Checkbox checked={delMedia} onCheckedChange={(v) => setDelMedia(!!v)} data-testid="del-media-checkbox" />
              <span className="text-sm">
                Удалить медиафайлы на хостинге
                <span className="block text-xs text-zinc-400">(фото и видео из R2/хранилища — освободит место)</span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} className="rounded-none border-zinc-200" data-testid="del-cancel">Отмена</Button>
            <Button onClick={confirmDelete} disabled={deleting} className="rounded-none bg-[#FF3333] hover:bg-[#CC0000] text-white" data-testid="del-confirm">
              {deleting ? "Удаляю…" : "Удалить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 bg-[#0055FF] flex items-center justify-center">
              <Bot className="h-5 w-5 text-white" strokeWidth={2.2} />
            </div>
            <div>
              <div className="text-base font-black tracking-tighter leading-none">MEDIA POST BOT</div>
              <div className="label-caps text-zinc-400 mt-0.5">Telegraph Control Room</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {selectedChannel && channels.length > 0 && (
              <>
                <div className="flex items-center gap-2 mr-1 pr-2 border-r border-zinc-200" data-testid="header-channel-box">
                  <Layers className="h-4 w-4 text-[#0055FF]" />
                  <select
                    value={selectedChannel}
                    onChange={(e) => { setSelectedChannel(e.target.value); setPage(1); }}
                    className="py-2 px-2 border border-zinc-200 text-sm outline-none focus:border-[#0055FF] bg-white max-w-[180px] font-semibold"
                    data-testid="header-channel-select"
                  >
                    {channels.map((c) => <option key={c.id} value={c.id}>{c.channel_title}</option>)}
                  </select>
                  <button
                    onClick={() => { setSelectedChannel(""); setPage(1); }}
                    className="text-xs text-zinc-400 hover:text-[#0055FF] whitespace-nowrap"
                    title="Сменить канал"
                    data-testid="change-channel-btn"
                  >
                    сменить
                  </button>
                </div>
              </>
            )}
            <Button onClick={() => setSchedulerOpen(true)} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="scheduler-settings-btn">
              <CalendarClock className="h-4 w-4 mr-2" /> Каналы и план
            </Button>
            <Button onClick={() => setWatermarkOpen(true)} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="watermark-settings-btn">
              <Droplets className="h-4 w-4 mr-2" /> Знак
            </Button>
            <Button onClick={load} variant="outline" className="rounded-none border-zinc-200" data-testid="refresh-btn">
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button onClick={logout} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="logout-btn">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {channelsLoaded && !selectedChannel && (
        <main className="max-w-4xl mx-auto px-6 py-16" data-testid="channel-gate">
          {channels.length === 0 ? (
            <div className="bg-white border border-zinc-200 p-16 text-center">
              <Radio className="h-12 w-12 text-zinc-300 mx-auto mb-5" />
              <h1 className="text-3xl font-black tracking-tighter mb-2">Каналов пока нет</h1>
              <p className="text-zinc-500 max-w-md mx-auto mb-6">Добавьте Telegram-канал, чтобы начать создавать и публиковать посты. Бот должен быть администратором канала.</p>
              <Button onClick={() => setSchedulerOpen(true)} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="gate-add-channel-btn">
                <Plus className="h-4 w-4 mr-2" /> Добавить канал
              </Button>
            </div>
          ) : (
            <div>
              <div className="mb-8">
                <span className="label-caps text-zinc-400">Начало работы</span>
                <h1 className="text-4xl sm:text-5xl font-black tracking-tighter mt-2">Выберите канал</h1>
                <p className="text-zinc-500 mt-2 max-w-2xl">Выберите канал, с которым будете работать. Статистика и список постов будут показаны только для него.</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {channels.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => { setSelectedChannel(c.id); setPage(1); }}
                    className="text-left bg-white border-2 border-zinc-200 p-6 hover:border-[#0055FF] hover:shadow-sm transition-all duration-150 group"
                    data-testid={`gate-channel-${c.id}`}
                  >
                    <div className="flex items-center gap-3 mb-3">
                      <div className="h-11 w-11 bg-[#0055FF] flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform duration-150">
                        <Radio className="h-5 w-5 text-white" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-bold tracking-tight truncate">{c.channel_title}</p>
                        {c.channel_username && <p className="text-xs text-zinc-400 truncate">@{c.channel_username}</p>}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-zinc-500">
                      <span className={`inline-flex items-center gap-1 ${c.enabled ? "text-[#00CC66]" : "text-zinc-400"}`}>
                        <span className={`h-2 w-2 rounded-full ${c.enabled ? "bg-[#00CC66]" : "bg-zinc-300"}`} />
                        {c.enabled ? "Авто-публикация вкл" : "Авто-публикация выкл"}
                      </span>
                    </div>
                  </button>
                ))}
                <button
                  onClick={() => setSchedulerOpen(true)}
                  className="flex flex-col items-center justify-center gap-2 border-2 border-dashed border-zinc-300 p-6 text-zinc-500 hover:border-[#0055FF] hover:text-[#0055FF] transition-colors duration-150 min-h-[132px]"
                  data-testid="gate-manage-channels-btn"
                >
                  <Plus className="h-6 w-6" />
                  <span className="text-sm font-semibold">Добавить / управлять каналами</span>
                </button>
              </div>
            </div>
          )}
        </main>
      )}

      {selectedChannel && (
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-start justify-between mb-8 gap-4 flex-wrap">
          <div>
            <span className="label-caps text-zinc-400" data-testid="current-channel-name">Канал: {currentChannel?.channel_title || "—"}</span>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tighter mt-1">Панель постов</h1>
            <p className="text-zinc-500 mt-2 max-w-2xl">Статистика и посты показаны только для выбранного канала. Сменить канал можно в шапке.</p>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={() => setBulkOpen(true)} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="bulk-replace-btn">
              <Replace className="h-4 w-4 mr-2" /> Заменить в описаниях
            </Button>
            <Button onClick={() => navigate("/new")} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="new-post-btn">
              <Plus className="h-4 w-4 mr-2" /> Новый пост
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          <StatCard label="Всего постов" value={stats?.total_posts ?? "—"} icon={FileText} testid="stat-total" />
          <StatCard label="Опубликовано" value={stats?.total_published ?? "—"} icon={Radio} accent="#00CC66" testid="stat-published" />
          <StatCard label="Черновики" value={stats?.total_drafts ?? "—"} icon={FileText} accent="#FF3333" testid="stat-drafts" />
          <StatCard label="Медиа-файлов" value={stats?.total_media ?? "—"} icon={ImageIcon} accent="#0055FF" testid="stat-media" />
          <StatCard label="В очереди" value={stats?.in_queue ?? "—"} icon={ListPlus} accent="#D97706" testid="stat-queue"
            sub={queueEndsAt ? <><CalendarClock className="h-3 w-3" /> закончится {fmtUTC(queueEndsAt)}</> : null} />
        </div>

        {jobs.length > 0 && (
          <div className="mb-8 space-y-3" data-testid="upload-jobs">
            {jobs.map((j) => (
              <div key={j.id} className="bg-white border border-zinc-200 p-4" data-testid={`upload-job-${j.id}`}>
                <div className="flex items-center justify-between mb-2 gap-3">
                  <span className="font-semibold text-sm truncate flex items-center gap-2">
                    <UploadCloud className="h-4 w-4 text-[#0055FF]" /> {j.title}
                  </span>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs text-zinc-500" data-testid={`upload-job-status-${j.id}`}>
                      {j.done}/{j.total} · {jobLabel(j)}
                    </span>
                    {j.status === "failed" && (
                      <>
                        <Button onClick={() => retryJob(j.id)} size="sm" className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white h-7 text-xs" data-testid={`upload-retry-${j.id}`}>
                          <RefreshCw className="h-3 w-3 mr-1" /> Повторить
                        </Button>
                        <button onClick={() => dismissJob(j.id)} className="text-zinc-400 hover:text-[#FF3333]" data-testid={`upload-dismiss-${j.id}`}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <div className="h-2 bg-zinc-100 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-200 ${j.status === "failed" ? "bg-[#FF3333]" : "bg-[#0055FF]"}`}
                    style={{ width: `${jobPct(j)}%` }}
                    data-testid={`upload-job-bar-${j.id}`}
                  />
                </div>
                {j.status === "failed" && j.error && (
                  <p className="text-xs text-[#FF3333] mt-2" data-testid={`upload-job-error-${j.id}`}>Файл {(j.nextIdx ?? 0) + 1}: {j.error}</p>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="bg-white border border-zinc-200" data-testid="posts-table">
          <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between gap-4 flex-wrap">
            <span className="label-caps text-zinc-500">История постов</span>
            <div className="flex items-center gap-3 flex-wrap">
              <select
                value={sortBy}
                onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
                className="py-2 px-2 border border-zinc-200 text-sm outline-none focus:border-[#0055FF] bg-white"
                data-testid="sort-by"
              >
                <option value="date">По дате</option>
                <option value="title">По названию</option>
                <option value="photos">По кол-ву фото</option>
                <option value="videos">По кол-ву видео</option>
                <option value="channel">По каналу</option>
                <option value="status">По статусу</option>
              </select>
              <button
                onClick={() => { setSortDir((d) => (d === "asc" ? "desc" : "asc")); setPage(1); }}
                className="p-2 border border-zinc-200 text-zinc-500 hover:text-[#0055FF] hover:border-[#0055FF]"
                title={sortDir === "asc" ? "По возрастанию" : "По убыванию"}
                data-testid="sort-dir"
              >
                <ArrowUpDown className="h-4 w-4" />
              </button>
              <div className="relative">
                <Search className="h-4 w-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  value={qInput}
                  onChange={(e) => setQInput(e.target.value)}
                  placeholder="Поиск по заголовку…"
                  className="pl-9 pr-3 py-2 border border-zinc-200 text-sm outline-none focus:border-[#0055FF] w-56"
                  data-testid="posts-search"
                />
              </div>
              <span className="text-sm text-zinc-400 whitespace-nowrap" data-testid="table-channel-label">В канале: {currentChannel?.channel_title || "—"}</span>
            </div>
          </div>

          {loading ? (
            <div className="p-12 text-center text-zinc-400">Загрузка...</div>
          ) : posts.length === 0 ? (
            <div className="p-16 text-center">
              <FileText className="h-10 w-10 text-zinc-300 mx-auto mb-4" />
              <p className="text-zinc-500 font-medium">{q ? "Ничего не найдено" : "Постов пока нет"}</p>
              {!q && (
                <Button onClick={() => navigate("/new")} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white mt-4">
                  <Plus className="h-4 w-4 mr-2" /> Создать первый пост
                </Button>
              )}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent border-zinc-200">
                  <TableHead className="w-[60px]"></TableHead>
                  <TableHead className="label-caps text-zinc-500">Заголовок</TableHead>
                  <TableHead className="label-caps text-zinc-500">Описание</TableHead>
                  <TableHead className="label-caps text-zinc-500">Дата</TableHead>
                  <TableHead className="label-caps text-zinc-500 text-center">Медиа</TableHead>
                  <TableHead className="label-caps text-zinc-500">Ссылка</TableHead>
                  <TableHead className="label-caps text-zinc-500">Статус</TableHead>
                  <TableHead className="label-caps text-zinc-500 text-right">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {posts.map((p) => (
                  <TableRow key={p.id} className="border-zinc-100 hover:bg-zinc-50 transition-colors duration-150" data-testid={`post-row-${p.id}`}>
                    <TableCell>
                      {p.cover_url ? (
                        <img src={p.cover_url} alt="" className="h-10 w-10 object-cover border border-zinc-200 bg-zinc-50" data-testid={`thumb-${p.id}`} />
                      ) : (
                        <div className="h-10 w-10 bg-zinc-900 flex items-center justify-center" data-testid={`thumb-${p.id}`}>
                          {p.media_count > 0 ? <Film className="h-4 w-4 text-white" /> : <FileText className="h-4 w-4 text-white" />}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-semibold max-w-[240px] truncate">{p.title?.trim() ? p.title : <span className="text-zinc-400 italic font-normal">(без названия)</span>}</TableCell>
                    <TableCell className="text-sm text-zinc-500 max-w-[260px]" data-testid={`desc-${p.id}`}>
                      {p.preview?.trim() ? (
                        <span className="line-clamp-2" title={p.preview}>{p.preview}</span>
                      ) : (
                        <span className="text-zinc-300">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-zinc-500 whitespace-nowrap">{fmtDate(p.created_at)}</TableCell>
                    <TableCell className="text-center">
                      <div className="flex justify-center items-center gap-3 text-zinc-600">
                        <span className="flex items-center gap-1" title="Фото" data-testid={`photo-count-${p.id}`}>
                          <ImageIcon className="h-3.5 w-3.5" /> <span className="text-sm font-medium">{p.photo_count ?? 0}</span>
                        </span>
                        <span className="flex items-center gap-1" title="Видео" data-testid={`video-count-${p.id}`}>
                          <Film className="h-3.5 w-3.5" /> <span className="text-sm font-medium">{p.video_count ?? 0}</span>
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {p.channel_post_url && (
                        <a href={p.channel_post_url} target="_blank" rel="noreferrer" className="text-green-600 font-semibold text-xs hover:underline flex items-center gap-1 mb-1.5" data-testid={`channel-link-${p.id}`}>
                          <ExternalLink className="h-3 w-3" /> Открыть в канале
                        </a>
                      )}
                      {p.post_type === "native" ? (
                        <span className="text-xs text-zinc-500 flex items-center gap-1" data-testid={`native-label-${p.id}`}>
                          📎 альбом в канале
                        </span>
                      ) : p.photos_url || p.videos_url ? (
                        <div className="flex flex-col gap-1">
                          {p.photos_url && (
                            <div className="flex items-center gap-2" data-testid={`photos-link-${p.id}`}>
                              <a href={p.photos_url} target="_blank" rel="noreferrer" className="text-[#0055FF] font-mono text-xs hover:underline flex items-center gap-1">
                                📷 фото <ExternalLink className="h-3 w-3" />
                              </a>
                              <button onClick={() => copyLink(p.photos_url)} className="text-zinc-400 hover:text-zinc-900" data-testid={`copy-photos-${p.id}`}>
                                <Copy className="h-3 w-3" />
                              </button>
                            </div>
                          )}
                          {p.videos_url && (
                            <div className="flex items-center gap-2" data-testid={`videos-link-${p.id}`}>
                              <a href={p.videos_url} target="_blank" rel="noreferrer" className="text-[#0055FF] font-mono text-xs hover:underline flex items-center gap-1">
                                🎬 видео <ExternalLink className="h-3 w-3" />
                              </a>
                              <button onClick={() => copyLink(p.videos_url)} className="text-zinc-400 hover:text-zinc-900" data-testid={`copy-videos-${p.id}`}>
                                <Copy className="h-3 w-3" />
                              </button>
                            </div>
                          )}
                        </div>
                      ) : p.telegraph_url ? (
                        <div className="flex items-center gap-2">
                          <a href={p.telegraph_url} target="_blank" rel="noreferrer" className="text-[#0055FF] font-mono text-xs hover:underline flex items-center gap-1" data-testid={`open-link-${p.id}`}>
                            {p.telegraph_url.replace("https://", "").slice(0, 22)}… <ExternalLink className="h-3 w-3" />
                          </a>
                          <button onClick={() => copyLink(p.telegraph_url)} className="text-zinc-400 hover:text-zinc-900" data-testid={`copy-link-${p.id}`}>
                            <Copy className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-zinc-400 font-mono" data-testid={`no-link-${p.id}`}>
                          {p.status === "failed" ? "ошибка создания" : "создаётся…"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {(() => {
                        const st = p.published ? "published" : (p.status || "ready");
                        const m = STATUS_META[st] || STATUS_META.ready;
                        return (
                          <div className="flex flex-col gap-1 items-start">
                            <Badge variant="outline" className={`rounded-none font-bold ${m.cls}`} data-testid={`status-${p.id}`}>
                              {m.label}
                            </Badge>
                            {!p.published && p.scheduled_at && (
                              <span className="text-[11px] text-[#0055FF] flex items-center gap-1 whitespace-nowrap" data-testid={`scheduled-badge-${p.id}`}>
                                <CalendarClock className="h-3 w-3" /> {fmtUTC(p.scheduled_at)}
                              </span>
                            )}
                            {!p.published && !p.scheduled_at && p.in_queue && (
                              <span className="text-[11px] text-amber-600 flex items-center gap-1 whitespace-nowrap" data-testid={`queued-badge-${p.id}`}>
                                <ListPlus className="h-3 w-3" /> в очереди
                              </span>
                            )}
                            {(p.channel_title || chanName(p.channel_ref)) && (
                              <span className="text-[11px] text-zinc-400 truncate max-w-[130px]" data-testid={`post-channel-${p.id}`}>
                                → {p.channel_title || chanName(p.channel_ref)}
                              </span>
                            )}
                          </div>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button onClick={() => publish(p.id)} disabled={publishing === p.id || !(p.status === "ready" || p.status === "published")} size="sm" className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white h-8 disabled:opacity-40" data-testid={`publish-${p.id}`}>
                          <Send className="h-3.5 w-3.5 mr-1.5" /> {p.published ? "Ещё раз" : "Опубликовать"}
                        </Button>
                        <button onClick={() => openSchedule(p)} disabled={!(p.status === "ready" || p.status === "published")} className={`p-2 disabled:opacity-30 ${p.scheduled_at ? "text-[#0055FF]" : "text-zinc-400 hover:text-[#0055FF]"}`} title="Отложенная публикация" data-testid={`schedule-${p.id}`}>
                          <CalendarClock className="h-4 w-4" />
                        </button>
                        <button onClick={() => toggleQueue(p)} disabled={!(p.status === "ready" || p.status === "published")} className={`p-2 disabled:opacity-30 ${p.in_queue ? "text-amber-600" : "text-zinc-400 hover:text-amber-600"}`} title={p.in_queue ? "Убрать из очереди" : "Добавить в очередь"} data-testid={`queue-${p.id}`}>
                          <ListPlus className="h-4 w-4" />
                        </button>
                        <button onClick={() => navigate(`/edit/${p.id}`)} disabled={!(p.status === "ready" || p.status === "published")} className="p-2 text-zinc-400 hover:text-[#0055FF] disabled:opacity-30 disabled:hover:text-zinc-400" title="Редактировать" data-testid={`edit-${p.id}`}>
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => removePost(p)} className="p-2 text-zinc-400 hover:text-[#FF3333]" data-testid={`delete-${p.id}`}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {!loading && totalPages > 1 && (
            <div className="px-6 py-4 border-t border-zinc-200 flex items-center justify-between" data-testid="pagination">
              <span className="text-sm text-zinc-500">Страница {page} из {totalPages}</span>
              <div className="flex items-center gap-2">
                <Button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} variant="outline" size="sm" className="rounded-none border-zinc-200 disabled:opacity-40" data-testid="pagination-prev">
                  <ChevronLeft className="h-4 w-4 mr-1" /> Назад
                </Button>
                <Button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} variant="outline" size="sm" className="rounded-none border-zinc-200 disabled:opacity-40" data-testid="pagination-next">
                  Вперёд <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>
      )}
    </div>
  );
}
