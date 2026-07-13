import { useState, useRef, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Star, Save, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api";
import { MarkdownToolbar } from "@/components/MarkdownToolbar";

export default function EditPost() {
  const navigate = useNavigate();
  const { id } = useParams();
  const descRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [media, setMedia] = useState([]);
  const [link, setLink] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/posts/${id}/edit`);
        setTitle(data.title);
        setDescription(data.description || "");
        setMedia(data.media || []);
        setLink(data.telegraph_url);
      } catch (e) {
        toast.error(e.response?.data?.detail || "Не удалось загрузить пост");
        navigate("/");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, navigate]);

  const setCover = (idx) =>
    setMedia((prev) => prev.map((m) => ({ ...m, is_cover: m.kind === "photo" && m.idx === idx })));
  const updCaption = (idx, caption) =>
    setMedia((prev) => prev.map((m) => (m.idx === idx ? { ...m, caption } : m)));

  const save = async () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    setSaving(true);
    try {
      await api.put(`/posts/${id}`, {
        title: title.trim(),
        description: description.trim(),
        media: media.map((m) => ({ idx: m.idx, caption: m.caption || "", is_cover: !!m.is_cover })),
      });
      toast.success("Статья обновлена");
      navigate("/");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400">Загрузка...</div>;

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate("/")} className="flex items-center gap-2 text-zinc-600 hover:text-zinc-900" data-testid="edit-back">
            <ArrowLeft className="h-4 w-4" /> Назад
          </button>
          <Button onClick={save} disabled={saving} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="edit-save">
            <Save className="h-4 w-4 mr-2" /> {saving ? "Сохраняю…" : "Сохранить"}
          </Button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-8">
        <div>
          <span className="label-caps text-zinc-400">Редактирование поста</span>
          <Input data-testid="edit-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Заголовок статьи"
            className="rounded-none border-0 border-b-2 border-zinc-200 px-0 text-3xl font-black tracking-tight h-auto py-3 mt-2 focus-visible:ring-0 focus-visible:border-[#0055FF]" />
          {link && (
            <a href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[#0055FF] text-xs font-mono mt-2 hover:underline" data-testid="edit-link">
              {link.replace("https://", "")} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Описание</h2>
          <MarkdownToolbar textareaRef={descRef} value={description} onChange={setDescription} />
          <Textarea ref={descRef} data-testid="edit-description" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Текст статьи. Поддержка: **жирный**, *курсив*, [ссылка](url), # заголовок, > цитата" className="rounded-none min-h-[120px]" />
        </section>

        {media.length > 0 && (
          <section>
            <h2 className="text-lg font-bold tracking-tight mb-3">Медиа <span className="text-sm text-zinc-400">— подписи и обложка</span></h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {media.map((m) => (
                <div key={m.idx} className="bg-white border border-zinc-200 p-2" data-testid={`edit-media-${m.idx}`}>
                  {m.kind === "photo" ? (
                    <img src={m.url} alt="" className="h-40 w-full object-contain bg-zinc-50" />
                  ) : (
                    <video src={m.url} controls className="h-40 w-full bg-black" />
                  )}
                  <Input value={m.caption || ""} onChange={(e) => updCaption(m.idx, e.target.value)} placeholder="Подпись" className="rounded-none mt-2 text-xs h-8" data-testid={`edit-caption-${m.idx}`} />
                  {m.kind === "photo" && (
                    <button type="button" onClick={() => setCover(m.idx)}
                      className={`mt-2 w-full flex items-center justify-center gap-1.5 text-xs font-semibold py-1.5 border transition-colors duration-150 ${m.is_cover ? "bg-[#0055FF] text-white border-[#0055FF]" : "bg-white text-zinc-600 border-zinc-200 hover:border-zinc-400"}`}
                      data-testid={`edit-cover-${m.idx}`}>
                      <Star className="h-3.5 w-3.5" fill={m.is_cover ? "#fff" : "none"} /> {m.is_cover ? "Обложка" : "Сделать обложкой"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
