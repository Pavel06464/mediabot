import { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Image as ImageIcon, Film, Star, Trash2, Save, UploadCloud, Send, AlertTriangle, GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import api from "@/lib/api";
import { useUpload } from "@/context/UploadContext";
import { MarkdownToolbar } from "@/components/MarkdownToolbar";
import { HashtagsInput } from "@/components/HashtagsInput";
import SignaturesManager from "@/components/SignaturesManager";

let idc = 0;
const nid = () => `m${++idc}`;

async function fileHash(file) {
  try {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return `${file.name}-${file.size}-${file.lastModified}`; // fallback
  }
}

function Dropzone({ accept, multiple, onFiles, children, testid, inputTestid }) {
  const [drag, setDrag] = useState(false);
  const ref = useRef(null);
  const handle = (list) => {
    const files = Array.from(list || []);
    const isVid = accept === "video/*";
    const valid = files.filter((f) => f.type.startsWith(isVid ? "video/" : "image/"));
    if (!valid.length) return toast.error(isVid ? "Перетащите видео" : "Перетащите изображение");
    onFiles(multiple ? valid : [valid[0]]);
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
      <input ref={ref} type="file" accept={accept} multiple={multiple} hidden data-testid={inputTestid}
        onChange={(e) => { handle(e.target.files); e.target.value = ""; }} />
      {children}
    </div>
  );
}

export default function PostEditor() {
  const navigate = useNavigate();
  const { startJob } = useUpload();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState([]);
  const descRef = useRef(null);
  const [covers, setCovers] = useState([]); // до 3 обложек: {id, file, localUrl}
  const [photos, setPhotos] = useState([]);
  const [videos, setVideos] = useState([]);
  const [publishAfter, setPublishAfter] = useState(false);
  const [postType, setPostType] = useState("telegraph");
  const [popularTags, setPopularTags] = useState([]);
  const [titleWarn, setTitleWarn] = useState(false);
  const [channels, setChannels] = useState([]);
  const [channelRef, setChannelRef] = useState("");
  const [signatures, setSignatures] = useState([]);
  const [sigOpen, setSigOpen] = useState(false);

  const loadSignatures = useCallback(() => {
    api.get("/signatures").then(({ data }) => setSignatures(data.signatures || [])).catch(() => {});
  }, []);

  const insertSignature = (id) => {
    const sig = signatures.find((s) => s.id === id);
    if (!sig) return;
    setDescription((prev) => (prev.trim() ? `${prev.trimEnd()}\n\n${sig.content}` : sig.content));
    toast.success(`Подпись «${sig.name}» вставлена`);
  };

  useEffect(() => {
    api.get("/hashtags/popular?limit=10").then(({ data }) => setPopularTags((data.tags || []).map((t) => t.tag))).catch(() => {});
    api.get("/channels").then(({ data }) => {
      const list = data.channels || [];
      setChannels(list);
      const preferred = localStorage.getItem("selected_channel");
      if (list.length) setChannelRef(list.some((c) => c.id === preferred) ? preferred : list[0].id);
    }).catch(() => {});
    loadSignatures();
  }, [loadSignatures]);

  useEffect(() => {
    const t = title.trim();
    if (!t) { setTitleWarn(false); return; }
    const id = setTimeout(async () => {
      try {
        const { data } = await api.get(`/posts/check-title?title=${encodeURIComponent(t)}`);
        setTitleWarn(!!data.exists);
      } catch { setTitleWarn(false); }
    }, 500);
    return () => clearTimeout(id);
  }, [title]);

  const onCover = useCallback((files) => {
    setCovers((prev) => {
      const room = 3 - prev.length;
      if (room <= 0) { toast.error("Можно не больше 3 обложек"); return prev; }
      const add = files.slice(0, room).map((f) => ({ id: nid(), file: f, localUrl: URL.createObjectURL(f) }));
      if (files.length > room) toast.info("Добавлено 3 обложки (максимум)");
      return [...prev, ...add];
    });
  }, []);
  const removeCover = (id) => setCovers((prev) => prev.filter((c) => c.id !== id));
  const addMedia = useCallback(async (files, kind) => {
    if (kind === "video") {
      setVideos((prev) => [...prev, ...files.map((f) => ({ id: nid(), file: f, localUrl: URL.createObjectURL(f), caption: "" }))]);
      return;
    }
    // фото: пропускаем побайтовые дубликаты (внутри текущего поста)
    const hashed = await Promise.all(files.map(async (f) => ({ f, h: await fileHash(f) })));
    setPhotos((prev) => {
      const seen = new Set(prev.map((p) => p.hash).filter(Boolean));
      const added = [];
      let dups = 0;
      for (const { f, h } of hashed) {
        if (seen.has(h)) { dups += 1; continue; }
        seen.add(h);
        added.push({ id: nid(), file: f, localUrl: URL.createObjectURL(f), caption: "", hash: h });
      }
      if (dups > 0) toast.info(`Пропущено дубликатов фото: ${dups}`);
      return [...prev, ...added];
    });
  }, []);
  const updCaption = (kind, id, caption) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.map((x) => (x.id === id ? { ...x, caption } : x)));
  };
  const removeItem = (kind, id) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.filter((x) => x.id !== id));
  };

  // ── Drag-and-drop переупорядочивание медиа ──
  const dragItem = useRef(null); // {list, index}
  const [dragOver, setDragOver] = useState(null); // {list, index}
  const SETTERS = { covers: setCovers, photos: setPhotos, videos: setVideos };
  const onDragStart = (list, index) => { dragItem.current = { list, index }; };
  const onDragEnter = (list, index) => {
    if (dragItem.current && dragItem.current.list === list) setDragOver({ list, index });
  };
  const onDragEnd = () => { dragItem.current = null; setDragOver(null); };
  const onDrop = (list, to) => {
    const from = dragItem.current;
    dragItem.current = null;
    setDragOver(null);
    if (!from || from.list !== list || from.index === to) return;
    SETTERS[list]((prev) => {
      const arr = [...prev];
      const [moved] = arr.splice(from.index, 1);
      arr.splice(to, 0, moved);
      return arr;
    });
  };
  const dropProps = (list, index) => ({
    onDragEnter: () => onDragEnter(list, index),
    onDragOver: (e) => e.preventDefault(),
    onDrop: () => onDrop(list, index),
  });
  const handleProps = (list, index) => ({
    draggable: true,
    onDragStart: () => onDragStart(list, index),
    onDragEnd: onDragEnd,
  });
  const dragCls = (list, index) =>
    dragOver?.list === list && dragOver?.index === index ? " ring-2 ring-[#0055FF] ring-offset-1" : "";

  const create = () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    if (!covers.length && !photos.length && !videos.length && !description.trim())
      return toast.error("Добавьте обложку, медиа или описание");
    if (publishAfter && postType === "telegraph" && !covers.length && !photos.length)
      return toast.error("Для публикации Telegraph-поста добавьте хотя бы одно фото (обложку)");
    if (publishAfter && postType === "native" && !covers.length && !photos.length && !videos.length)
      return toast.error("Для публикации добавьте хотя бы одно медиа");

    const items = [];
    covers.forEach((c) => items.push({ kind: "photo", is_cover: true, caption: "", file: c.file }));
    photos.forEach((p) => items.push({ kind: "photo", is_cover: false, caption: p.caption, file: p.file }));
    videos.forEach((v) => items.push({ kind: "video", is_cover: false, caption: v.caption, file: v.file }));

    startJob({ meta: { title: title.trim(), description: description.trim(), publish_after: publishAfter, hashtags, post_type: postType, channel_ref: channelRef || null }, items });
    toast.info("Загрузка началась — следите за прогрессом на дашборде");
    navigate("/");
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate("/")} className="flex items-center gap-2 text-zinc-600 hover:text-zinc-900" data-testid="editor-back">
            <ArrowLeft className="h-4 w-4" /> Назад
          </button>
          <Button onClick={create} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="editor-save">
            <Save className="h-4 w-4 mr-2" /> {postType === "native" ? "Создать пост" : "Создать статью"}
          </Button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-8">
        <div>
          <span className="label-caps text-zinc-400">Новый пост</span>
          <Input data-testid="editor-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Заголовок"
            className="rounded-none border-0 border-b-2 border-zinc-200 px-0 text-3xl font-black tracking-tight h-auto py-3 mt-2 focus-visible:ring-0 focus-visible:border-[#0055FF]" />
          {titleWarn && (
            <p className="text-xs text-amber-600 mt-2 flex items-center gap-1.5" data-testid="title-dup-warning">
              <AlertTriangle className="h-3.5 w-3.5" /> Пост с таким названием уже существует
            </p>
          )}
        </div>

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Тип публикации</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button type="button" onClick={() => setPostType("telegraph")}
              className={`text-left p-4 border-2 transition-colors duration-150 ${postType === "telegraph" ? "border-[#0055FF] bg-blue-50" : "border-zinc-200 bg-white hover:border-zinc-300"}`}
              data-testid="type-telegraph">
              <p className="font-bold text-sm">Telegraph-статья</p>
              <p className="text-xs text-zinc-500 mt-1">Ссылка на статью с большим предпросмотром. Подходит для больших альбомов и видео.</p>
            </button>
            <button type="button" onClick={() => setPostType("native")}
              className={`text-left p-4 border-2 transition-colors duration-150 ${postType === "native" ? "border-[#0055FF] bg-blue-50" : "border-zinc-200 bg-white hover:border-zinc-300"}`}
              data-testid="type-native">
              <p className="font-bold text-sm">Обычный пост (альбом)</p>
              <p className="text-xs text-zinc-500 mt-1">Медиа прямо в канал альбомами по 10, с подписью и хештегами. Без ссылки.</p>
            </button>
          </div>
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Star className="h-4 w-4 text-[#0055FF]" fill="#0055FF" />
            <h2 className="text-lg font-bold tracking-tight">Обложка / превью</h2>
            <span className="text-sm text-zinc-400">— до 3 фото. Одно фото — большой предпросмотр, 2–3 — альбом в канале</span>
          </div>
          {covers.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3" data-testid="covers-list">
              {covers.map((c, i) => (
                <div key={c.id} {...dropProps("covers", i)} className={`relative bg-white border border-zinc-200 p-2${dragCls("covers", i)}`} data-testid={`cover-item-${i}`}>
                  <img src={c.localUrl} alt="cover" className="h-40 w-full object-contain bg-zinc-50 pointer-events-none" />
                  <span className="absolute top-3 left-3 bg-[#0055FF] text-white text-[11px] font-bold px-1.5 py-0.5">{i + 1}</span>
                  <span {...handleProps("covers", i)} className="absolute bottom-3 left-3 bg-white/90 border border-zinc-200 p-1 text-zinc-500 hover:text-[#0055FF] cursor-move" title="Перетащите для изменения порядка" data-testid={`cover-drag-${i}`}>
                    <GripVertical className="h-4 w-4" />
                  </span>
                  <button onClick={() => removeCover(c.id)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]" data-testid={`cover-remove-${i}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
          {covers.length < 3 && (
            <Dropzone accept="image/*" multiple onFiles={onCover} testid="cover-dropzone" inputTestid="cover-file-input">
              <UploadCloud className="h-7 w-7 text-zinc-400 mx-auto mb-2" />
              <p className="text-sm text-zinc-600 font-medium">Перетащите фото сюда или нажмите</p>
              <p className="text-xs text-zinc-400 mt-1">до 3 изображений ({covers.length}/3)</p>
            </Dropzone>
          )}
        </section>

        <section>
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h2 className="text-lg font-bold tracking-tight">Описание</h2>
            <div className="flex items-center gap-2">
              {signatures.length > 0 && (
                <select
                  value=""
                  onChange={(e) => { insertSignature(e.target.value); e.target.value = ""; }}
                  className="border border-zinc-200 px-2 py-1.5 text-sm outline-none focus:border-[#0055FF] bg-white"
                  data-testid="insert-signature"
                >
                  <option value="">+ Вставить подпись…</option>
                  {signatures.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              )}
              <button onClick={() => setSigOpen(true)} className="text-sm text-[#0055FF] hover:underline whitespace-nowrap" data-testid="manage-signatures-btn">
                Подписи
              </button>
            </div>
          </div>
          <MarkdownToolbar textareaRef={descRef} value={description} onChange={setDescription} />
          <Textarea ref={descRef} data-testid="editor-description" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Текст статьи (необязательно). Поддержка: **жирный**, *курсив*, [ссылка](url) — ссылка прячется за текстом, # заголовок, > цитата" className="rounded-none min-h-[120px]" />
        </section>

        <SignaturesManager open={sigOpen} onOpenChange={setSigOpen} onChange={loadSignatures} />

        <section>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-lg font-bold tracking-tight">Хештеги</h2>
            <span className="text-sm text-zinc-400">— добавятся в сообщение канала (не в статью)</span>
          </div>
          <HashtagsInput tags={hashtags} setTags={setHashtags} suggestions={popularTags} />
        </section>

        {channels.length > 0 && (
          <section>
            <h2 className="text-lg font-bold tracking-tight mb-3">Канал публикации</h2>
            <select
              value={channelRef}
              onChange={(e) => setChannelRef(e.target.value)}
              className="w-full border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-[#0055FF] bg-white"
              data-testid="editor-channel"
            >
              {channels.map((c) => <option key={c.id} value={c.id}>{c.channel_title}</option>)}
            </select>
          </section>
        )}

        <section>
          <div className="flex items-center gap-2 mb-3">
            <ImageIcon className="h-4 w-4 text-zinc-700" />
            <h2 className="text-lg font-bold tracking-tight">Фотографии</h2>
            {photos.length > 0 && <span className="text-sm text-zinc-400">— {photos.length}</span>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
            {photos.map((p, i) => (
              <div key={p.id} {...dropProps("photos", i)} className={`relative bg-white border border-zinc-200 p-1.5${dragCls("photos", i)}`} data-testid={`photo-item-${p.id}`}>
                <img src={p.localUrl} alt="" className="h-28 w-full object-cover bg-zinc-50 pointer-events-none" />
                <span {...handleProps("photos", i)} className="absolute bottom-11 left-2 bg-white/90 border border-zinc-200 p-1 text-zinc-500 hover:text-[#0055FF] cursor-move" title="Перетащите для изменения порядка" data-testid={`photo-drag-${i}`}>
                  <GripVertical className="h-3.5 w-3.5" />
                </span>
                <button onClick={() => removeItem("photo", p.id)} className="absolute top-2 right-2 bg-white border border-zinc-200 p-1 text-zinc-500 hover:text-[#FF3333]">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                <Input value={p.caption} onChange={(e) => updCaption("photo", p.id, e.target.value)} placeholder="Подпись" className="rounded-none mt-1.5 text-xs h-8" />
              </div>
            ))}
          </div>
          <Dropzone accept="image/*" multiple onFiles={(f) => addMedia(f, "photo")} testid="photos-dropzone" inputTestid="photos-file-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите фотографии сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Film className="h-4 w-4 text-zinc-700" />
            <h2 className="text-lg font-bold tracking-tight">Видео</h2>
            {videos.length > 0 && <span className="text-sm text-zinc-400">— {videos.length}</span>}
          </div>
          <div className="space-y-3 mb-3">
            {videos.map((v, i) => (
              <div key={v.id} {...dropProps("videos", i)} className={`relative bg-white border border-zinc-200 p-2${dragCls("videos", i)}`} data-testid={`video-item-${v.id}`}>
                <video src={v.localUrl} controls className="max-h-56 w-full bg-black" />
                <span {...handleProps("videos", i)} className="absolute top-3 left-3 bg-white/90 border border-zinc-200 p-1 text-zinc-500 hover:text-[#0055FF] cursor-move" title="Перетащите для изменения порядка" data-testid={`video-drag-${i}`}>
                  <GripVertical className="h-4 w-4" />
                </span>
                <button onClick={() => removeItem("video", v.id)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]">
                  <Trash2 className="h-4 w-4" />
                </button>
                <Input value={v.caption} onChange={(e) => updCaption("video", v.id, e.target.value)} placeholder="Подпись" className="rounded-none mt-2 text-sm" />
              </div>
            ))}
          </div>
          <Dropzone accept="video/*" multiple onFiles={(f) => addMedia(f, "video")} testid="videos-dropzone" inputTestid="videos-file-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите видео сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>

        <section className="flex items-center justify-between border border-zinc-200 bg-white p-4">
          <div className="flex items-center gap-2">
            <Send className="h-4 w-4 text-[#0055FF]" />
            <div>
              <div className="font-semibold text-sm">Опубликовать в канал после загрузки</div>
              <div className="text-xs text-zinc-400">Статья автоматически уйдёт в канал, когда медиа загрузятся</div>
            </div>
          </div>
          <Switch checked={publishAfter} onCheckedChange={setPublishAfter} data-testid="publish-after-toggle" />
        </section>
      </main>
    </div>
  );
}
