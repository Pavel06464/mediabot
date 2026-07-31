import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Star, Save, ExternalLink, Trash2, UploadCloud, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api";
import { MarkdownToolbar } from "@/components/MarkdownToolbar";
import { HashtagsInput } from "@/components/HashtagsInput";

let nc = 0;
const nid = () => `n${++nc}`;

function Dropzone({ accept, onFiles, children, testid, inputTestid }) {
  const [drag, setDrag] = useState(false);
  const ref = useRef(null);
  const handle = (list) => {
    const files = Array.from(list || []);
    const isVid = accept === "video/*";
    const valid = files.filter((f) => f.type.startsWith(isVid ? "video/" : "image/"));
    if (!valid.length) return toast.error(isVid ? "Перетащите видео" : "Перетащите изображение");
    onFiles(valid);
  };
  return (
    <div
      data-testid={testid}
      onClick={() => ref.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files); }}
      className={`cursor-pointer border-2 border-dashed p-6 text-center transition-colors duration-150 ${drag ? "border-[#0055FF] bg-blue-50" : "border-zinc-300 bg-zinc-50 hover:border-zinc-400"}`}
    >
      <input ref={ref} type="file" accept={accept} multiple hidden data-testid={inputTestid}
        onChange={(e) => { handle(e.target.files); e.target.value = ""; }} />
      {children}
    </div>
  );
}

export default function EditPost() {
  const navigate = useNavigate();
  const { id } = useParams();
  const descRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState([]);
  const [media, setMedia] = useState([]);
  const [newMedia, setNewMedia] = useState([]); // {tempId, kind, localUrl, uploading, url, media_id, r2_key, caption}
  const [link, setLink] = useState(null);
  const [channels, setChannels] = useState([]);
  const [channelRef, setChannelRef] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [{ data }, chRes] = await Promise.all([
          api.get(`/posts/${id}/edit`),
          api.get("/channels").catch(() => ({ data: { channels: [] } })),
        ]);
        setTitle(data.title);
        setDescription(data.description || "");
        setHashtags(data.hashtags || []);
        setMedia(data.media || []);
        setLink(data.telegraph_url);
        setChannels(chRes.data.channels || []);
        setChannelRef(data.channel_ref || chRes.data.channels?.[0]?.id || "");
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
  const removeMedia = (idx) =>
    setMedia((prev) => prev.filter((m) => m.idx !== idx));

  const uploadNew = useCallback((files, kind) => {
    files.forEach((file) => {
      const tempId = nid();
      const localUrl = URL.createObjectURL(file);
      setNewMedia((prev) => [...prev, { tempId, kind, localUrl, uploading: true, caption: "" }]);
      const form = new FormData();
      form.append("file", file);
      api.post(`/posts/${id}/media`, form)
        .then(({ data }) => {
          setNewMedia((prev) => prev.map((m) => m.tempId === tempId
            ? { ...m, uploading: false, url: data.url, media_id: data.media_id, r2_key: data.r2_key }
            : m));
        })
        .catch((e) => {
          toast.error(e.response?.data?.detail || "Ошибка загрузки файла");
          setNewMedia((prev) => prev.filter((m) => m.tempId !== tempId));
        });
    });
  }, [id]);

  const updNewCaption = (tempId, caption) =>
    setNewMedia((prev) => prev.map((m) => (m.tempId === tempId ? { ...m, caption } : m)));
  const removeNew = (tempId) =>
    setNewMedia((prev) => prev.filter((m) => m.tempId !== tempId));

  const save = async () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    if (newMedia.some((m) => m.uploading)) return toast.error("Дождитесь загрузки новых файлов");
    setSaving(true);
    try {
      await api.put(`/posts/${id}`, {
        title: title.trim(),
        description: description.trim(),
        hashtags,
        media: media.map((m) => ({ idx: m.idx, caption: m.caption || "", is_cover: !!m.is_cover })),
        new_media: newMedia.filter((m) => m.url).map((m) => ({
          kind: m.kind, url: m.url, media_id: m.media_id, r2_key: m.r2_key, caption: m.caption || "", is_cover: false,
        })),
        channel_ref: channelRef || null,
      });
      toast.success("Пост обновлён");
      navigate("/");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400">Загрузка...</div>;

  const newPhotos = newMedia.filter((m) => m.kind === "photo");
  const newVideos = newMedia.filter((m) => m.kind === "video");

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

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Хештеги</h2>
          <HashtagsInput tags={hashtags} setTags={setHashtags} />
        </section>

        {channels.length > 0 && (
          <section>
            <h2 className="text-lg font-bold tracking-tight mb-3">Канал публикации</h2>
            <select
              value={channelRef}
              onChange={(e) => setChannelRef(e.target.value)}
              className="w-full border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF] bg-white"
              data-testid="edit-channel"
            >
              {channels.map((c) => <option key={c.id} value={c.id}>{c.channel_title}</option>)}
            </select>
            <p className="text-xs text-zinc-400 mt-2">В какой канал отправлять этот пост при публикации.</p>
          </section>
        )}

        {media.length > 0 && (
          <section>
            <h2 className="text-lg font-bold tracking-tight mb-3">Медиа <span className="text-sm text-zinc-400">— подписи, обложка, удаление</span></h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {media.map((m) => (
                <div key={m.idx} className="bg-white border border-zinc-200 p-2 relative" data-testid={`edit-media-${m.idx}`}>
                  <button type="button" onClick={() => removeMedia(m.idx)}
                    className="absolute top-3 right-3 z-10 bg-white/90 border border-zinc-200 text-zinc-600 hover:text-white hover:bg-[#FF3333] hover:border-[#FF3333] p-1.5 transition-colors duration-150"
                    title="Удалить медиа" data-testid={`edit-remove-${m.idx}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
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
            <p className="text-xs text-zinc-400 mt-3">Удалённые медиа исчезнут из статьи и с хостинга после сохранения.</p>
          </section>
        )}

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Добавить фотографии</h2>
          {newPhotos.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
              {newPhotos.map((m) => (
                <div key={m.tempId} className="relative bg-white border border-zinc-200 p-1.5" data-testid={`new-photo-${m.tempId}`}>
                  <img src={m.localUrl} alt="" className="h-28 w-full object-cover bg-zinc-50" />
                  {m.uploading && (
                    <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                      <Loader2 className="h-6 w-6 text-white animate-spin" />
                    </div>
                  )}
                  <button onClick={() => removeNew(m.tempId)} className="absolute top-2 right-2 bg-white border border-zinc-200 p-1 text-zinc-500 hover:text-[#FF3333]" data-testid={`new-photo-remove-${m.tempId}`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  <Input value={m.caption} onChange={(e) => updNewCaption(m.tempId, e.target.value)} placeholder="Подпись" className="rounded-none mt-1.5 text-xs h-8" />
                </div>
              ))}
            </div>
          )}
          <Dropzone accept="image/*" onFiles={(f) => uploadNew(f, "photo")} testid="edit-photos-dropzone" inputTestid="edit-photos-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите фотографии сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Добавить видео</h2>
          {newVideos.length > 0 && (
            <div className="space-y-3 mb-3">
              {newVideos.map((m) => (
                <div key={m.tempId} className="relative bg-white border border-zinc-200 p-2" data-testid={`new-video-${m.tempId}`}>
                  <video src={m.localUrl} controls className="max-h-56 w-full bg-black" />
                  {m.uploading && (
                    <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                      <Loader2 className="h-7 w-7 text-white animate-spin" />
                    </div>
                  )}
                  <button onClick={() => removeNew(m.tempId)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]" data-testid={`new-video-remove-${m.tempId}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <Input value={m.caption} onChange={(e) => updNewCaption(m.tempId, e.target.value)} placeholder="Подпись" className="rounded-none mt-2 text-sm" />
                </div>
              ))}
            </div>
          )}
          <Dropzone accept="video/*" onFiles={(f) => uploadNew(f, "video")} testid="edit-videos-dropzone" inputTestid="edit-videos-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите видео сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>
      </main>
    </div>
  );
}
