import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import { toast } from "sonner";
import api from "@/lib/api";

const UploadContext = createContext(null);

const STALL_MS = 90000; // если данные не идут 90с — считаем обрыв и повторяем
const MAX_ATTEMPTS = 3;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function errMsg(err) {
  if (err?.response) {
    const s = err.response.status;
    if (s === 413) return "файл слишком большой (лимит сервера nginx)";
    if (s === 400) return err.response.data?.detail || "неверный файл";
    return err.response.data?.detail || `ошибка сервера (${s})`;
  }
  if (err?.code === "ERR_CANCELED") return "обрыв связи (нет передачи данных)";
  return "нет связи с сервером";
}

export function UploadProvider({ children }) {
  const [jobs, setJobs] = useState([]);
  const jobsRef = useRef([]);
  useEffect(() => { jobsRef.current = jobs; }, [jobs]);

  const patch = (id, fn) => setJobs((prev) => prev.map((j) => (j.id === id ? fn(j) : j)));
  const removeLater = (id) => setTimeout(() => setJobs((prev) => prev.filter((x) => x.id !== id)), 6000);

  // Загрузка одного файла со stall-таймаутом (abort, если нет прогресса STALL_MS)
  const uploadOne = (postId, slot, file, onProg) => {
    const controller = new AbortController();
    let timer;
    const resetStall = () => {
      clearTimeout(timer);
      timer = setTimeout(() => controller.abort(), STALL_MS);
    };
    resetStall();
    const fd = new FormData();
    fd.append("file", file);
    return api
      .post(`/posts/${postId}/media/${slot}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        signal: controller.signal,
        onUploadProgress: (e) => {
          resetStall();
          onProg(e.total ? Math.round((e.loaded / e.total) * 100) : 0);
        },
      })
      .finally(() => clearTimeout(timer));
  };

  const pollStatus = useCallback((postId) => {
    const poll = async () => {
      try {
        const { data } = await api.get(`/posts/${postId}`);
        if (data.status === "ready" || data.status === "published") {
          patch(postId, (j) => ({ ...j, status: "done" }));
          toast.success(data.published ? `Опубликовано в «${data.channel_title}»` : "Статья готова");
          removeLater(postId);
        } else if (data.status === "failed") {
          patch(postId, (j) => ({ ...j, status: "failed", error: data.error || "не удалось создать статью" }));
          toast.error(data.error || "Не удалось создать статью");
        } else {
          setTimeout(poll, 1500);
        }
      } catch {
        setTimeout(poll, 2500);
      }
    };
    poll();
  }, []);

  // Загружает слоты начиная с индекса startIdx; при обрыве — ретраи, затем стоп с возможностью «Повторить»
  const runUploads = useCallback((postId, items, slots, meta, startIdx) => {
    (async () => {
      for (let k = startIdx; k < items.length; k++) {
        let ok = false;
        for (let attempt = 1; attempt <= MAX_ATTEMPTS && !ok; attempt++) {
          patch(postId, (j) => ({ ...j, status: "uploading", attempt, pct: 0, error: null }));
          try {
            await uploadOne(postId, slots[k], items[k].file, (p) => patch(postId, (j) => ({ ...j, pct: p })));
            ok = true;
          } catch (err) {
            const msg = errMsg(err);
            const permanent = err?.response && [400, 413].includes(err.response.status);
            if (attempt >= MAX_ATTEMPTS || permanent) {
              patch(postId, (j) => ({ ...j, status: "failed", nextIdx: k, error: msg }));
              toast.error(`«${meta.title}» — файл ${k + 1}: ${msg}`);
              return;
            }
            await sleep(1500 * attempt);
          }
        }
        patch(postId, (j) => ({ ...j, done: k + 1, pct: 0 }));
      }
      patch(postId, (j) => ({ ...j, status: "processing", pct: 100 }));
      pollStatus(postId);
    })();
  }, [pollStatus]);

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
      { id: postId, title: meta.title, total: items.length, done: 0, pct: 0, status: "uploading", items, slots, meta, nextIdx: 0 },
      ...prev,
    ]);
    if (items.length === 0) { pollStatus(postId); return; }
    runUploads(postId, items, slots, meta, 0);
  }, [runUploads, pollStatus]);

  const retryJob = useCallback((postId) => {
    const job = jobsRef.current.find((j) => j.id === postId);
    if (!job || !job.items) return;
    const from = job.nextIdx ?? job.done ?? 0;
    runUploads(postId, job.items, job.slots, job.meta, from);
  }, [runUploads]);

  const dismissJob = useCallback((postId) => {
    setJobs((prev) => prev.filter((x) => x.id !== postId));
  }, []);

  return (
    <UploadContext.Provider value={{ jobs, startJob, retryJob, dismissJob }}>
      {children}
    </UploadContext.Provider>
  );
}

export const useUpload = () => useContext(UploadContext);
