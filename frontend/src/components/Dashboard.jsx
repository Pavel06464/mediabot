import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Send,
  FileText,
  Radio,
  Image as ImageIcon,
  Film,
  ExternalLink,
  Copy,
  Trash2,
  RefreshCw,
  Bot,
  ArrowUpRight,
  Layers,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};

function StatCard({ label, value, icon: Icon, accent, testid }) {
  return (
    <div
      data-testid={testid}
      className="bg-white border border-zinc-200 p-6 flex flex-col justify-between hover:border-zinc-400 transition-colors duration-150"
    >
      <div className="flex items-center justify-between">
        <span className="label-caps text-zinc-500">{label}</span>
        <Icon className="h-4 w-4 text-zinc-400" strokeWidth={2} />
      </div>
      <div
        className="mt-6 text-5xl font-black tracking-tighter"
        style={{ color: accent || "#09090B" }}
      >
        {value}
      </div>
    </div>
  );
}

function MediaBadge({ post }) {
  return (
    <div className="flex items-center gap-1.5 text-zinc-600">
      <Layers className="h-3.5 w-3.5" strokeWidth={2} />
      <span className="text-sm font-medium">{post.media_count}</span>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [channels, setChannels] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, p, c] = await Promise.all([
        axios.get(`${API}/stats`),
        axios.get(`${API}/posts`),
        axios.get(`${API}/channels`),
      ]);
      setStats(s.data);
      setPosts(p.data);
      setChannels(c.data);
    } catch (e) {
      toast.error("Не удалось загрузить данные");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const copyLink = (url) => {
    navigator.clipboard.writeText(url);
    toast.success("Ссылка скопирована");
  };

  const removePost = async (id) => {
    try {
      await axios.delete(`${API}/posts/${id}`);
      toast.success("Пост удалён");
      setSelected(null);
      load();
    } catch {
      toast.error("Ошибка удаления");
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 bg-[#0055FF] flex items-center justify-center">
              <Bot className="h-5 w-5 text-white" strokeWidth={2.2} />
            </div>
            <div>
              <div className="text-base font-black tracking-tighter leading-none">
                MEDIA POST BOT
              </div>
              <div className="label-caps text-zinc-400 mt-0.5">
                Telegraph Control Room
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://t.me/pdmtelegraphbot"
              target="_blank"
              rel="noreferrer"
              data-testid="open-bot-link"
            >
              <Button
                variant="outline"
                className="rounded-none border-zinc-200 hover:bg-zinc-100"
              >
                <Send className="h-4 w-4 mr-2" /> Открыть бота
              </Button>
            </a>
            <Button
              onClick={load}
              className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white"
              data-testid="refresh-btn"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-8">
          <h1 className="text-4xl sm:text-5xl font-black tracking-tighter">
            Панель постов
          </h1>
          <p className="text-zinc-500 mt-2 max-w-2xl">
            Все статьи Telegraph, созданные через вашего Telegram-бота, с ссылками
            для публикации и статусом канала.
          </p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Всего постов"
            value={stats?.total_posts ?? "—"}
            icon={FileText}
            testid="stat-total"
          />
          <StatCard
            label="Опубликовано"
            value={stats?.total_published ?? "—"}
            icon={Radio}
            accent="#00CC66"
            testid="stat-published"
          />
          <StatCard
            label="Черновики"
            value={stats?.total_drafts ?? "—"}
            icon={FileText}
            accent="#FF3333"
            testid="stat-drafts"
          />
          <StatCard
            label="Медиа-файлов"
            value={stats?.total_media ?? "—"}
            icon={ImageIcon}
            accent="#0055FF"
            testid="stat-media"
          />
        </div>

        {/* Posts table */}
        <div className="bg-white border border-zinc-200" data-testid="posts-table">
          <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between">
            <span className="label-caps text-zinc-500">История постов</span>
            <span className="text-sm text-zinc-400">
              {channels.length} канал(ов) подключено
            </span>
          </div>

          {loading ? (
            <div className="p-12 text-center text-zinc-400">Загрузка...</div>
          ) : posts.length === 0 ? (
            <div className="p-16 text-center">
              <FileText className="h-10 w-10 text-zinc-300 mx-auto mb-4" />
              <p className="text-zinc-500 font-medium">Постов пока нет</p>
              <p className="text-zinc-400 text-sm mt-1">
                Создайте первый пост в Telegram-боте — он появится здесь.
              </p>
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {posts.map((p) => (
                  <TableRow
                    key={p.id}
                    className="border-zinc-100 cursor-pointer hover:bg-zinc-50 transition-colors duration-150 group"
                    onClick={() => setSelected(p)}
                    data-testid={`post-row-${p.id}`}
                  >
                    <TableCell>
                      <div className="h-10 w-10 bg-zinc-900 flex items-center justify-center">
                        {p.media_count > 0 ? (
                          <Film className="h-4 w-4 text-white" />
                        ) : (
                          <FileText className="h-4 w-4 text-white" />
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-semibold max-w-[280px] truncate">
                      {p.title}
                    </TableCell>
                    <TableCell className="text-sm text-zinc-500 whitespace-nowrap">
                      {fmtDate(p.created_at)}
                    </TableCell>
                    <TableCell className="text-center">
                      <div className="flex justify-center">
                        <MediaBadge post={p} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <a
                          href={p.telegraph_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-[#0055FF] font-mono text-xs hover:underline flex items-center gap-1"
                          data-testid={`open-link-${p.id}`}
                        >
                          {p.telegraph_url.replace("https://", "")}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            copyLink(p.telegraph_url);
                          }}
                          className="text-zinc-400 hover:text-zinc-900 transition-colors"
                          data-testid={`copy-link-${p.id}`}
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </TableCell>
                    <TableCell>
                      {p.published ? (
                        <Badge
                          className="rounded-none bg-[#00CC66] hover:bg-[#00CC66] text-white font-bold"
                          data-testid={`status-${p.id}`}
                        >
                          В КАНАЛЕ
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="rounded-none border-zinc-300 text-zinc-500 font-bold"
                          data-testid={`status-${p.id}`}
                        >
                          ЧЕРНОВИК
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </main>

      {/* Detail sheet */}
      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent className="rounded-none sm:max-w-lg overflow-y-auto" data-testid="post-detail">
          {selected && (
            <>
              <SheetHeader>
                <span className="label-caps text-zinc-400">Детали поста</span>
                <SheetTitle className="text-2xl font-black tracking-tight text-left">
                  {selected.title}
                </SheetTitle>
                <SheetDescription className="sr-only">
                  Детали созданного поста Telegraph
                </SheetDescription>
              </SheetHeader>

              <div className="mt-6 space-y-6">
                <div className="flex items-center gap-2">
                  {selected.published ? (
                    <Badge className="rounded-none bg-[#00CC66] text-white font-bold">
                      ОПУБЛИКОВАН
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="rounded-none border-zinc-300 font-bold">
                      ЧЕРНОВИК
                    </Badge>
                  )}
                  {selected.channel_title && (
                    <span className="text-sm text-zinc-500">
                      → {selected.channel_title}
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="border border-zinc-200 p-4">
                    <span className="label-caps text-zinc-400">Медиа</span>
                    <div className="text-2xl font-black mt-1">{selected.media_count}</div>
                  </div>
                  <div className="border border-zinc-200 p-4">
                    <span className="label-caps text-zinc-400">Блоков</span>
                    <div className="text-2xl font-black mt-1">{selected.block_count}</div>
                  </div>
                </div>

                {selected.preview && (
                  <div>
                    <span className="label-caps text-zinc-400">Превью текста</span>
                    <p className="mt-2 text-sm text-zinc-600 border-l-2 border-zinc-200 pl-3">
                      {selected.preview}
                    </p>
                  </div>
                )}

                <div>
                  <span className="label-caps text-zinc-400">Ссылка Telegraph</span>
                  <div className="mt-2 flex items-center gap-2 border border-zinc-200 p-3">
                    <span className="font-mono text-xs text-zinc-700 truncate flex-1">
                      {selected.telegraph_url}
                    </span>
                    <button
                      onClick={() => copyLink(selected.telegraph_url)}
                      className="text-zinc-400 hover:text-zinc-900"
                      data-testid="detail-copy-link"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="flex flex-col gap-2 pt-2">
                  <a href={selected.telegraph_url} target="_blank" rel="noreferrer">
                    <Button
                      className="w-full rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white"
                      data-testid="detail-open-btn"
                    >
                      Открыть статью <ArrowUpRight className="h-4 w-4 ml-2" />
                    </Button>
                  </a>
                  <Button
                    variant="outline"
                    onClick={() => removePost(selected.id)}
                    className="w-full rounded-none border-zinc-200 text-[#FF3333] hover:bg-red-50 hover:text-[#FF3333]"
                    data-testid="detail-delete-btn"
                  >
                    <Trash2 className="h-4 w-4 mr-2" /> Удалить пост
                  </Button>
                </div>

                <p className="text-xs text-zinc-400 pt-4 border-t border-zinc-100">
                  Публикация в канал доступна прямо в Telegram-боте после создания поста.
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
