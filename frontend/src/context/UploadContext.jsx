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
        toast.error(err.response?.data?.detail || `Ошибка загрузки файла ${k + 1}`);
        return;
      }
    }

    // Медиа загружены — сервер оформляет статью в Telegraph. Ждём готовности.
    patch(postId, (j) => ({ ...j, status: "processing", pct: 100 }));
    const finish = () => setTimeout(() => setJobs((prev) => prev.filter((x) => x.id !== postId)), 5000);
    const poll = async () => {
      try {
        const { data } = await api.get(`/posts/${postId}`);
        if (data.status === "ready" || data.status === "published") {
          patch(postId, (j) => ({ ...j, status: "done" }));
          toast.success(data.published ? `Опубликовано в «${data.channel_title}»` : "Статья готова");
          finish();
        } else if (data.status === "failed") {
          patch(postId, (j) => ({ ...j, status: "failed" }));
          toast.error(data.error || "Не удалось создать статью");
          finish();
        } else {
          setTimeout(poll, 1500);
        }
      } catch {
        setTimeout(poll, 2000);
      }
    };
    poll();
  }, []);

  return <UploadContext.Provider value={{ jobs, startJob }}>{children}</UploadContext.Provider>;
}

export const useUpload = () => useContext(UploadContext);
