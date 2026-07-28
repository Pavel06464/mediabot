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
} from "lucide-react";
import { Button } from "@/components/ui/button";
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

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
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

function StatCard({ label, value, icon: Icon, accent, testid }) {
  return (
    <div data-testid={testid} className="bg-white border border-zinc-200 p-6 flex flex-col justify-between hover:border-zinc-400 transition-colors duration-150">
      <div className="flex items-center justify-between">
        <span className="label-caps text-zinc-500">{label}</span>
        <Icon className="h-4 w-4 text-zinc-400" strokeWidth={2} />
      </div>
      <div className="mt-6 text-5xl font-black tracking-tighter" style={{ color: accent || "#09090B" }}>{value}</div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { jobs, retryJob, dismissJob } = useUpload();
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [channel, setChannel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(null);
  const [channelOpen, setChannelOpen] = useState(false);
  const [watermarkOpen, setWatermarkOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [delChannel, setDelChannel] = useState(false);
  const [delMedia, setDelMedia] = useState(true);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p, c] = await Promise.all([
        api.get("/stats"),
        api.get(`/posts?page=${page}&page_size=20&q=${encodeURIComponent(q)}`),
        api.get("/settings"),
      ]);
      setStats(s.data);
      setPosts(p.data.items);
      setTotalPages(p.data.pages);
      setChannel(c.data.channel_id ? c.data : null);
    } catch (e) {
      // 401 handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [page, q]);

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
    if (!channel) { toast.error("Сначала настройте канал"); setChannelOpen(true); return; }
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

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <ChannelSettings open={channelOpen} onOpenChange={setChannelOpen} onChange={load} />
      <WatermarkSettings open={watermarkOpen} onOpenChange={setWatermarkOpen} />

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
            <Button onClick={() => setWatermarkOpen(true)} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="watermark-settings-btn">
              <Droplets className="h-4 w-4 mr-2" /> Знак
            </Button>
            <Button onClick={() => setChannelOpen(true)} variant="outline" className="rounded-none border-zinc-200 hover:bg-zinc-100" data-testid="channel-settings-btn">
              <Settings className="h-4 w-4 mr-2" /> {channel ? channel.channel_title : "Канал"}
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

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-start justify-between mb-8 gap-4 flex-wrap">
          <div>
            <h1 className="text-4xl sm:text-5xl font-black tracking-tighter">Панель постов</h1>
            <p className="text-zinc-500 mt-2 max-w-2xl">Создавайте статьи Telegraph с медиа и публикуйте их в канал прямо отсюда.</p>
          </div>
          <Button onClick={() => navigate("/new")} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="new-post-btn">
            <Plus className="h-4 w-4 mr-2" /> Новый пост
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="Всего постов" value={stats?.total_posts ?? "—"} icon={FileText} testid="stat-total" />
          <StatCard label="Опубликовано" value={stats?.total_published ?? "—"} icon={Radio} accent="#00CC66" testid="stat-published" />
          <StatCard label="Черновики" value={stats?.total_drafts ?? "—"} icon={FileText} accent="#FF3333" testid="stat-drafts" />
          <StatCard label="Медиа-файлов" value={stats?.total_media ?? "—"} icon={ImageIcon} accent="#0055FF" testid="stat-media" />
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
            <div className="flex items-center gap-4">
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
              <span className="text-sm text-zinc-400 whitespace-nowrap">{channel ? `Канал: ${channel.channel_title}` : "Канал не настроен"}</span>
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
                    <TableCell className="font-semibold max-w-[240px] truncate">{p.title}</TableCell>
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
                          <Badge variant="outline" className={`rounded-none font-bold ${m.cls}`} data-testid={`status-${p.id}`}>
                            {m.label}
                          </Badge>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button onClick={() => publish(p.id)} disabled={publishing === p.id || !(p.status === "ready" || p.status === "published")} size="sm" className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white h-8 disabled:opacity-40" data-testid={`publish-${p.id}`}>
                          <Send className="h-3.5 w-3.5 mr-1.5" /> {p.published ? "Ещё раз" : "Опубликовать"}
                        </Button>
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
    </div>
  );
}
