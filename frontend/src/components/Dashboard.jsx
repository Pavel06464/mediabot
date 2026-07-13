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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import ChannelSettings from "@/components/ChannelSettings";
import WatermarkSettings from "@/components/WatermarkSettings";

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
};

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
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [channel, setChannel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(null);
  const [channelOpen, setChannelOpen] = useState(false);
  const [watermarkOpen, setWatermarkOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p, c] = await Promise.all([
        api.get("/stats"), api.get("/posts"), api.get("/settings"),
      ]);
      setStats(s.data);
      setPosts(p.data);
      setChannel(c.data.channel_id ? c.data : null);
    } catch (e) {
      // 401 handled by interceptor
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

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

  const removePost = async (id) => {
    try { await api.delete(`/posts/${id}`); toast.success("Пост удалён"); load(); }
    catch { toast.error("Ошибка удаления"); }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <ChannelSettings open={channelOpen} onOpenChange={setChannelOpen} onChange={load} />
      <WatermarkSettings open={watermarkOpen} onOpenChange={setWatermarkOpen} />

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

        <div className="bg-white border border-zinc-200" data-testid="posts-table">
          <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between">
            <span className="label-caps text-zinc-500">История постов</span>
            <span className="text-sm text-zinc-400">{channel ? `Канал: ${channel.channel_title}` : "Канал не настроен"}</span>
          </div>

          {loading ? (
            <div className="p-12 text-center text-zinc-400">Загрузка...</div>
          ) : posts.length === 0 ? (
            <div className="p-16 text-center">
              <FileText className="h-10 w-10 text-zinc-300 mx-auto mb-4" />
              <p className="text-zinc-500 font-medium">Постов пока нет</p>
              <Button onClick={() => navigate("/new")} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white mt-4">
                <Plus className="h-4 w-4 mr-2" /> Создать первый пост
              </Button>
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
                      <div className="h-10 w-10 bg-zinc-900 flex items-center justify-center">
                        {p.media_count > 0 ? <Film className="h-4 w-4 text-white" /> : <FileText className="h-4 w-4 text-white" />}
                      </div>
                    </TableCell>
                    <TableCell className="font-semibold max-w-[240px] truncate">{p.title}</TableCell>
                    <TableCell className="text-sm text-zinc-500 whitespace-nowrap">{fmtDate(p.created_at)}</TableCell>
                    <TableCell className="text-center">
                      <div className="flex justify-center items-center gap-1.5 text-zinc-600">
                        <Layers className="h-3.5 w-3.5" /> <span className="text-sm font-medium">{p.media_count}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <a href={p.telegraph_url} target="_blank" rel="noreferrer" className="text-[#0055FF] font-mono text-xs hover:underline flex items-center gap-1" data-testid={`open-link-${p.id}`}>
                          {p.telegraph_url.replace("https://", "").slice(0, 22)}… <ExternalLink className="h-3 w-3" />
                        </a>
                        <button onClick={() => copyLink(p.telegraph_url)} className="text-zinc-400 hover:text-zinc-900" data-testid={`copy-link-${p.id}`}>
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </TableCell>
                    <TableCell>
                      {p.published ? (
                        <Badge className="rounded-none bg-[#00CC66] hover:bg-[#00CC66] text-white font-bold" data-testid={`status-${p.id}`}>В КАНАЛЕ</Badge>
                      ) : (
                        <Badge variant="outline" className="rounded-none border-zinc-300 text-zinc-500 font-bold" data-testid={`status-${p.id}`}>ЧЕРНОВИК</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button onClick={() => publish(p.id)} disabled={publishing === p.id} size="sm" className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white h-8" data-testid={`publish-${p.id}`}>
                          <Send className="h-3.5 w-3.5 mr-1.5" /> {p.published ? "Ещё раз" : "Опубликовать"}
                        </Button>
                        <button onClick={() => removePost(p.id)} className="p-2 text-zinc-400 hover:text-[#FF3333]" data-testid={`delete-${p.id}`}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </main>
    </div>
  );
}
