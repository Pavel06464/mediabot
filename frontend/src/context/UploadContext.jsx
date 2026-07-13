import { createContext, useContext, useState, useCallback } from "react";
import { toast } from "sonner";
import api from "@/lib/api";

const UploadContext = createContext(null);

export function UploadProvider({ children }) {
  const [jobs, setJobs] = useState([]);

  const patch = (id, fn) => setJobs((prev) => prev.map((j) => (j.id === id ? fn(j) : j)));

  const startJob = useCallback(async ({ meta, items }) => {
    let draft;
    try {
      const media = items.map((i) => ({ kind: i.kind, is_cover: !!i.is_cover, caption: i.caption || "" }));
      const { data } = await api.post("/posts/draft", { ...meta, media });
      draft = data;
    } catch (e) {
      toast.error("Не удалось создать черновик");
      return;
    }
    const postId = draft.id;
    const slots = draft.slots;
    setJobs((prev) => [
      { id: postId, title: meta.title, total: items.length, done: 0, pct: 0, status: "uploading" },
      ...prev,
    ]);

    for (let k = 0; k < items.length; k++) {
      const fd = new FormData();
      fd.append("file", items[k].file);
      try {
        await api.post(`/posts/${postId}/media/${slots[k]}`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (e) => {
            const p = e.total ? Math.round((e.loaded / e.total) * 100) : 0;
            patch(postId, (j) => ({ ...j, pct: p }));
          },
        });
        patch(postId, (j) => ({ ...j, done: j.done + 1, pct: 0 }));
      } catch (err) {
        patch(postId, (j) => ({ ...j, status: "failed" }));
        toast.error(`Ошибка загрузки файла ${k + 1}`);
        return;
      }
    }
    patch(postId, (j) => ({ ...j, status: "done" }));
    toast.success(meta.publish_after ? "Загрузка завершена — публикую в канал" : "Статья готова");
    setTimeout(() => setJobs((prev) => prev.filter((x) => x.id !== postId)), 5000);
  }, []);

  return <UploadContext.Provider value={{ jobs, startJob }}>{children}</UploadContext.Provider>;
}

export const useUpload = () => useContext(UploadContext);
