import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft,
  Type,
  Image as ImageIcon,
  Film,
  Trash2,
  ChevronUp,
  ChevronDown,
  Star,
  Loader2,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import api, { apiError } from "@/lib/api";

let idc = 0;
const nid = () => `b${++idc}`;

export default function PostEditor() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [blocks, setBlocks] = useState([]);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);
  const pendingKind = useRef("photo");

  const addText = () =>
    setBlocks((b) => [...b, { id: nid(), type: "text", value: "", caption: "" }]);

  const pickFile = (kind) => {
    pendingKind.current = kind;
    fileRef.current.accept = kind === "video" ? "video/*" : "image/*";
    fileRef.current.value = "";
    fileRef.current.click();
  };

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const kind = pendingKind.current;
    const tmpId = nid();
    setBlocks((b) => [...b, { id: tmpId, type: kind, url: "", caption: "", uploading: true, is_cover: false }]);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setBlocks((b) =>
        b.map((x) => (x.id === tmpId ? { ...x, url: data.url, media_id: data.media_id, uploading: false } : x))
      );
      toast.success(kind === "video" ? "Видео загружено" : "Фото загружено");
    } catch (err) {
      setBlocks((b) => b.filter((x) => x.id !== tmpId));
      toast.error(apiError(err.response?.data?.detail) || "Ошибка загрузки");
    }
  };

  const update = (id, patch) => setBlocks((b) => b.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const remove = (id) => setBlocks((b) => b.filter((x) => x.id !== id));
  const move = (id, dir) =>
    setBlocks((b) => {
      const i = b.findIndex((x) => x.id === id);
      const j = i + dir;
      if (j < 0 || j >= b.length) return b;
      const copy = [...b];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  const setCover = (id) =>
    setBlocks((b) => b.map((x) => ({ ...x, is_cover: x.id === id ? !x.is_cover : false })));

  const save = async () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    if (blocks.length === 0) return toast.error("Добавьте хотя бы один блок");
    if (blocks.some((b) => b.uploading)) return toast.error("Дождитесь загрузки медиа");
    setSaving(true);
    try {
      const payload = {
        title: title.trim(),
        blocks: blocks.map((b) => ({
          type: b.type,
          url: b.url || null,
          media_id: b.media_id || null,
          caption: b.caption || "",
          value: b.value || null,
          is_cover: !!b.is_cover,
        })),
      };
      const { data } = await api.post("/posts", payload);
      toast.success("Статья создана!");
      navigate("/", { state: { createdUrl: data.telegraph_url } });
    } catch (err) {
      toast.error(apiError(err.response?.data?.detail) || "Ошибка создания");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <input ref={fileRef} type="file" hidden onChange={onFile} data-testid="hidden-file-input" />

      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 text-zinc-600 hover:text-zinc-900"
            data-testid="editor-back"
          >
            <ArrowLeft className="h-4 w-4" /> Назад
          </button>
          <Button
            onClick={save}
            disabled={saving}
            className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white"
            data-testid="editor-save"
          >
            {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            Создать статью
          </Button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        <span className="label-caps text-zinc-400">Новый пост</span>
        <Input
          data-testid="editor-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Заголовок статьи"
          className="rounded-none border-0 border-b-2 border-zinc-200 px-0 text-3xl font-black tracking-tight h-auto py-3 mt-2 focus-visible:ring-0 focus-visible:border-[#0055FF]"
        />

        <div className="mt-6 space-y-3" data-testid="blocks-list">
          {blocks.map((b, idx) => (
            <div key={b.id} className="bg-white border border-zinc-200 p-4" data-testid={`block-${idx}`}>
              <div className="flex items-center justify-between mb-3">
                <span className="label-caps text-zinc-400 flex items-center gap-1.5">
                  {b.type === "text" ? <Type className="h-3.5 w-3.5" /> : b.type === "video" ? <Film className="h-3.5 w-3.5" /> : <ImageIcon className="h-3.5 w-3.5" />}
                  {b.type === "text" ? "Текст" : b.type === "video" ? "Видео" : "Фото"}
                </span>
                <div className="flex items-center gap-1">
                  {(b.type === "photo" || b.type === "video") && (
                    <button
                      onClick={() => setCover(b.id)}
                      title="Сделать обложкой"
                      className={`p-1.5 transition-colors ${b.is_cover ? "text-[#0055FF]" : "text-zinc-400 hover:text-zinc-900"}`}
                      data-testid={`block-cover-${idx}`}
                    >
                      <Star className="h-4 w-4" fill={b.is_cover ? "#0055FF" : "none"} />
                    </button>
                  )}
                  <button onClick={() => move(b.id, -1)} className="p-1.5 text-zinc-400 hover:text-zinc-900" data-testid={`block-up-${idx}`}>
                    <ChevronUp className="h-4 w-4" />
                  </button>
                  <button onClick={() => move(b.id, 1)} className="p-1.5 text-zinc-400 hover:text-zinc-900" data-testid={`block-down-${idx}`}>
                    <ChevronDown className="h-4 w-4" />
                  </button>
                  <button onClick={() => remove(b.id)} className="p-1.5 text-zinc-400 hover:text-[#FF3333]" data-testid={`block-delete-${idx}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {b.type === "text" ? (
                <Textarea
                  data-testid={`block-text-${idx}`}
                  value={b.value}
                  onChange={(e) => update(b.id, { value: e.target.value })}
                  placeholder="Введите текст абзаца..."
                  className="rounded-none min-h-[90px]"
                />
              ) : (
                <div>
                  {b.uploading ? (
                    <div className="h-40 bg-zinc-50 border border-dashed border-zinc-300 flex items-center justify-center text-zinc-400">
                      <Loader2 className="h-5 w-5 animate-spin mr-2" /> Загрузка...
                    </div>
                  ) : b.type === "video" ? (
                    <video src={b.url} controls className="max-h-64 w-full bg-black" />
                  ) : (
                    <img src={b.url} alt="" className="max-h-64 w-full object-contain bg-zinc-50" />
                  )}
                  {b.is_cover && (
                    <div className="mt-2 label-caps text-[#0055FF] flex items-center gap-1">
                      <Star className="h-3 w-3" fill="#0055FF" /> Обложка / предпросмотр
                    </div>
                  )}
                  <Input
                    value={b.caption}
                    onChange={(e) => update(b.id, { caption: e.target.value })}
                    placeholder="Подпись (необязательно)"
                    className="rounded-none mt-2 text-sm"
                    data-testid={`block-caption-${idx}`}
                  />
                </div>
              )}
            </div>
          ))}

          {blocks.length === 0 && (
            <div className="text-center py-12 text-zinc-400 border border-dashed border-zinc-300 bg-white">
              Добавьте блоки контента ниже
            </div>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Button onClick={addText} variant="outline" className="rounded-none border-zinc-300" data-testid="add-text">
            <Type className="h-4 w-4 mr-2" /> Текст
          </Button>
          <Button onClick={() => pickFile("photo")} variant="outline" className="rounded-none border-zinc-300" data-testid="add-photo">
            <ImageIcon className="h-4 w-4 mr-2" /> Фото
          </Button>
          <Button onClick={() => pickFile("video")} variant="outline" className="rounded-none border-zinc-300" data-testid="add-video">
            <Film className="h-4 w-4 mr-2" /> Видео
          </Button>
        </div>
      </main>
    </div>
  );
}
