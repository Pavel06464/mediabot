import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft,
  Image as ImageIcon,
  Film,
  Star,
  Trash2,
  Loader2,
  Save,
  UploadCloud,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import api, { apiError } from "@/lib/api";

let idc = 0;
const nid = () => `m${++idc}`;

async function uploadOne(file) {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await api.post("/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data; // {url, media_id?, type}
}

function Dropzone({ accept, multiple, onFiles, children, testid, inputTestid }) {
  const [drag, setDrag] = useState(false);
  const ref = useRef(null);

  const handleFiles = (fileList) => {
    const files = Array.from(fileList || []);
    const kind = accept === "video/*" ? "video" : "image";
    const valid = files.filter((f) => f.type.startsWith(kind === "video" ? "video/" : "image/"));
    if (valid.length === 0) {
      toast.error(kind === "video" ? "Перетащите видеофайл" : "Перетащите изображение");
      return;
    }
    onFiles(multiple ? valid : [valid[0]]);
  };

  return (
    <div
      data-testid={testid}
      onClick={() => ref.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={`cursor-pointer border-2 border-dashed p-6 text-center transition-colors duration-150 ${
        drag ? "border-[#0055FF] bg-blue-50" : "border-zinc-300 bg-zinc-50 hover:border-zinc-400"
      }`}
    >
      <input
        ref={ref}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        data-testid={inputTestid}
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
      {children}
    </div>
  );
}

export default function PostEditor() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState(null); // {id,url,media_id,uploading}
  const [photos, setPhotos] = useState([]);
  const [videos, setVideos] = useState([]);
  const [saving, setSaving] = useState(false);

  const anyUploading =
    cover?.uploading || photos.some((p) => p.uploading) || videos.some((v) => v.uploading);

  const setCoverFiles = useCallback(async (files) => {
    const file = files[0];
    const id = nid();
    setCover({ id, url: "", uploading: true });
    try {
      const data = await uploadOne(file);
      setCover({ id, url: data.url, media_id: data.media_id, uploading: false });
      toast.success("Обложка загружена");
    } catch (err) {
      setCover(null);
      toast.error(apiError(err.response?.data?.detail) || "Ошибка загрузки");
    }
  }, []);

  const addMedia = useCallback((files, kind) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    files.forEach((file) => {
      const id = nid();
      setter((prev) => [...prev, { id, url: "", caption: "", uploading: true }]);
      uploadOne(file)
        .then((data) => {
          setter((prev) =>
            prev.map((x) => (x.id === id ? { ...x, url: data.url, media_id: data.media_id, uploading: false } : x))
          );
        })
        .catch((err) => {
          setter((prev) => prev.filter((x) => x.id !== id));
          toast.error(apiError(err.response?.data?.detail) || "Ошибка загрузки");
        });
    });
  }, []);

  const updateCaption = (kind, id, caption) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.map((x) => (x.id === id ? { ...x, caption } : x)));
  };
  const removeItem = (kind, id) => {
    const setter = kind === "video" ? setVideos : setPhotos;
    setter((prev) => prev.filter((x) => x.id !== id));
  };

  const save = async () => {
    if (!title.trim()) return toast.error("Укажите заголовок");
    if (!cover && photos.length === 0 && videos.length === 0 && !description.trim())
      return toast.error("Добавьте обложку, медиа или описание");
    if (anyUploading) return toast.error("Дождитесь загрузки медиа");

    const blocks = [];
    if (cover?.url)
      blocks.push({ type: "photo", url: cover.url, media_id: cover.media_id || null, caption: "", is_cover: true });
    if (description.trim())
      blocks.push({ type: "text", value: description.trim() });
    photos.forEach((p) =>
      p.url && blocks.push({ type: "photo", url: p.url, media_id: p.media_id || null, caption: p.caption || "", is_cover: false })
    );
    videos.forEach((v) =>
      v.url && blocks.push({ type: "video", url: v.url, media_id: v.media_id || null, caption: v.caption || "", is_cover: false })
    );

    setSaving(true);
    try {
      const { data } = await api.post("/posts", { title: title.trim(), blocks });
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
      <header className="sticky top-0 z-50 bg-white border-b border-zinc-200">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate("/")} className="flex items-center gap-2 text-zinc-600 hover:text-zinc-900" data-testid="editor-back">
            <ArrowLeft className="h-4 w-4" /> Назад
          </button>
          <Button onClick={save} disabled={saving} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="editor-save">
            {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            Создать статью
          </Button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-8">
        <div>
          <span className="label-caps text-zinc-400">Новый пост</span>
          <Input
            data-testid="editor-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Заголовок статьи"
            className="rounded-none border-0 border-b-2 border-zinc-200 px-0 text-3xl font-black tracking-tight h-auto py-3 mt-2 focus-visible:ring-0 focus-visible:border-[#0055FF]"
          />
        </div>

        {/* Обложка */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Star className="h-4 w-4 text-[#0055FF]" fill="#0055FF" />
            <h2 className="text-lg font-bold tracking-tight">Обложка / превью</h2>
            <span className="text-sm text-zinc-400">— 1 фото, станет предпросмотром ссылки</span>
          </div>
          {cover ? (
            <div className="relative bg-white border border-zinc-200 p-2 inline-block w-full">
              {cover.uploading ? (
                <div className="h-48 flex items-center justify-center text-zinc-400">
                  <Loader2 className="h-5 w-5 animate-spin mr-2" /> Загрузка...
                </div>
              ) : (
                <img src={cover.url} alt="cover" className="max-h-64 w-full object-contain bg-zinc-50" />
              )}
              <button onClick={() => setCover(null)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]" data-testid="cover-remove">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <Dropzone accept="image/*" multiple={false} onFiles={setCoverFiles} testid="cover-dropzone" inputTestid="cover-file-input">
              <UploadCloud className="h-7 w-7 text-zinc-400 mx-auto mb-2" />
              <p className="text-sm text-zinc-600 font-medium">Перетащите фото сюда или нажмите</p>
              <p className="text-xs text-zinc-400 mt-1">одно изображение</p>
            </Dropzone>
          )}
        </section>

        {/* Описание */}
        <section>
          <h2 className="text-lg font-bold tracking-tight mb-3">Описание</h2>
          <Textarea
            data-testid="editor-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Текст статьи (необязательно)"
            className="rounded-none min-h-[120px]"
          />
        </section>

        {/* Фотографии */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <ImageIcon className="h-4 w-4 text-zinc-700" />
            <h2 className="text-lg font-bold tracking-tight">Фотографии</h2>
            {photos.length > 0 && <span className="text-sm text-zinc-400">— {photos.length}</span>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
            {photos.map((p) => (
              <div key={p.id} className="relative bg-white border border-zinc-200 p-1.5" data-testid={`photo-item-${p.id}`}>
                {p.uploading ? (
                  <div className="h-28 flex items-center justify-center text-zinc-400"><Loader2 className="h-4 w-4 animate-spin" /></div>
                ) : (
                  <img src={p.url} alt="" className="h-28 w-full object-cover bg-zinc-50" />
                )}
                <button onClick={() => removeItem("photo", p.id)} className="absolute top-2 right-2 bg-white border border-zinc-200 p-1 text-zinc-500 hover:text-[#FF3333]">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                <Input value={p.caption} onChange={(e) => updateCaption("photo", p.id, e.target.value)} placeholder="Подпись" className="rounded-none mt-1.5 text-xs h-8" />
              </div>
            ))}
          </div>
          <Dropzone accept="image/*" multiple onFiles={(f) => addMedia(f, "photo")} testid="photos-dropzone" inputTestid="photos-file-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите фотографии сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>

        {/* Видео */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Film className="h-4 w-4 text-zinc-700" />
            <h2 className="text-lg font-bold tracking-tight">Видео</h2>
            {videos.length > 0 && <span className="text-sm text-zinc-400">— {videos.length}</span>}
          </div>
          <div className="space-y-3 mb-3">
            {videos.map((v) => (
              <div key={v.id} className="relative bg-white border border-zinc-200 p-2" data-testid={`video-item-${v.id}`}>
                {v.uploading ? (
                  <div className="h-40 flex items-center justify-center text-zinc-400"><Loader2 className="h-5 w-5 animate-spin mr-2" /> Загрузка...</div>
                ) : (
                  <video src={v.url} controls className="max-h-56 w-full bg-black" />
                )}
                <button onClick={() => removeItem("video", v.id)} className="absolute top-3 right-3 bg-white border border-zinc-200 p-1.5 text-zinc-500 hover:text-[#FF3333]">
                  <Trash2 className="h-4 w-4" />
                </button>
                <Input value={v.caption} onChange={(e) => updateCaption("video", v.id, e.target.value)} placeholder="Подпись" className="rounded-none mt-2 text-sm" />
              </div>
            ))}
          </div>
          <Dropzone accept="video/*" multiple onFiles={(f) => addMedia(f, "video")} testid="videos-dropzone" inputTestid="videos-file-input">
            <UploadCloud className="h-6 w-6 text-zinc-400 mx-auto mb-2" />
            <p className="text-sm text-zinc-600 font-medium">Перетащите видео сюда или нажмите</p>
            <p className="text-xs text-zinc-400 mt-1">можно несколько сразу</p>
          </Dropzone>
        </section>
      </main>
    </div>
  );
}
