import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Image as ImageIcon, Film, Star, Trash2, Save, UploadCloud, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { useUpload } from "@/context/UploadContext";
import { MarkdownToolbar } from "@/components/MarkdownToolbar";

let idc = 0;
const nid = () => `m${++idc}`;

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
  const descRef = useRef(null);
  const [cover, setCover] = useState(null); // {file, localUrl}
  const [photos, setPhotos] = useState([]);
  const [videos, setVideos] = useState([]);
  const [publishAfter, setPublishAfter] = useState(false);

  const onCover = useCallback((files) => {
    const f = files[0];
    setCover({ file: f, localUrl: URL.createObjectURL(f) });
  }, []);
  const addMedia = useCallback((files, kind) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => [...prev, ...files.map((f) => ({ id: nid(), file: f, localUrl: URL.createObjectURL(f), caption: "" }))]);
  }, []);
  const updCaption = (kind, id, caption) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.map((x) => (x.id === id ? { ...x, caption } : x)));
  };
  const removeItem = (kind, id) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.filter((x) => x.id !== id));
  };

  const create = () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    if (!cover && !photos.length && !videos.length && !description.trim())
      return toast.error("Добавьте обложку, медиа или описание");
    if (publishAfter && !cover && !photos.length)
      return toast.error("Для публикации добавьте хотя бы одно фото (обложку)");

    const items = [];
    if (cover?.file) items.push({ kind: "photo", is_cover: true, caption: "", file: cover.file });
    photos.forEach((p) => items.push({ kind: "photo", is_cover: false, caption: p.caption, file: p.file }));
    videos.forEach((v) => items.push({ kind: "video", is_cover: false, caption: v.caption, file: v.file }));

    startJob({ meta: { title: title.trim(), description: description.trim(), publish_after: publishAfter }, items });
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
            <Save className="h-4 w-4 mr-2" /> Создать статью
          </Button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-8">
        <div>
          <span className="label-caps text-zinc-400">Новый пост</span>
          <Input data-testid="editor-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Заголовок статьи"
            className="rounded-none border-0 border-b-2 border-zinc-200 px-0 text-3xl font-black tracking-tight h-auto py-3 mt-2 focus-visible:ring-0 focus-visible:border-[#0055FF]" />
        </div>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Star className="h-4 w-4 text-[#0055FF]" fill="#0055FF" />
            <h2 className="text-lg font-bold tracking-tight">Обложка / превью</h2>
            <span className="text-sm text-zinc-400">— 1 фото, большой предпросмотр в канале</span>
          </div>
          {cover ? (
            <div className="relative bg-white border border-zinc-200 p-2">
              <img src={cover.localUrl} alt="cover" className="max-h-64 w-full object-contain bg-zinc-50" />
              <button onClick={() => setCover(null)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]" data-testid="cover-remove">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <Dropzone accept="image/*" multiple={false} onFiles={onCover} testid="cover-dropzone" inputTestid="cover-file-input">
              <UploadCloud className="h-7 w-7 text-zinc-400 mx-auto mb-2" />
              <p className="text-sm text-zinc-600 font-medium">Перетащите фото сюда или нажмите</p>
              <p className="text-xs text-zinc-400 mt-1">одно изображение</p>
            </Dropzone>
          )}
        </section>

        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Описание</h2>
          <MarkdownToolbar textareaRef={descRef} value={description} onChange={setDescription} />
          <Textarea ref={descRef} data-testid="editor-description" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Текст статьи (необязательно). Поддержка: **жирный**, *курсив*, [ссылка](url), # заголовок, > цитата" className="rounded-none min-h-[120px]" />
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <ImageIcon className="h-4 w-4 text-zinc-700" />
            <h2 className="text-lg font-bold tracking-tight">Фотографии</h2>
            {photos.length > 0 && <span className="text-sm text-zinc-400">— {photos.length}</span>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
            {photos.map((p) => (
              <div key={p.id} className="relative bg-white border border-zinc-200 p-1.5" data-testid={`photo-item-${p.id}`}>
                <img src={p.localUrl} alt="" className="h-28 w-full object-cover bg-zinc-50" />
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
            {videos.map((v) => (
              <div key={v.id} className="relative bg-white border border-zinc-200 p-2" data-testid={`video-item-${v.id}`}>
                <video src={v.localUrl} controls className="max-h-56 w-full bg-black" />
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
