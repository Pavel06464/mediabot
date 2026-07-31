import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Trash2, Plus, Save, Pencil, Link2, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import api from "@/lib/api";

export default function SignaturesManager({ open, onOpenChange, onChange }) {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null); // {id?, name, content}

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/signatures");
      setItems(data.signatures || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { if (open) { load(); setEditing(null); } }, [open, load]);

  const save = async () => {
    if (!editing?.name?.trim()) return toast.error("Укажите название");
    try {
      if (editing.id) await api.put(`/signatures/${editing.id}`, { name: editing.name, content: editing.content });
      else await api.post("/signatures", { name: editing.name, content: editing.content });
      toast.success("Подпись сохранена");
      setEditing(null);
      load();
      onChange?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Ошибка"); }
  };

  const remove = async (id) => {
    try { await api.delete(`/signatures/${id}`); load(); onChange?.(); }
    catch { toast.error("Ошибка"); }
  };

  const insertLink = () => {
    setEditing((e) => ({ ...e, content: `${e.content || ""}[Надпись](https://ссылка)` }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none sm:max-w-lg max-h-[90vh] overflow-y-auto" data-testid="signatures-dialog">
        <DialogHeader>
          <DialogTitle>Подписи</DialogTitle>
          <DialogDescription>
            Готовые подписи для описания. Ссылку можно спрятать за текстом: <code className="text-[#0055FF]">[Надпись](https://ссылка)</code>. Эмодзи вставляйте как обычно (👉).
          </DialogDescription>
        </DialogHeader>

        {editing ? (
          <div className="space-y-3 py-1" data-testid="signature-form">
            <Input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              placeholder="Название (например: Полина)" className="rounded-none" data-testid="signature-name" />
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label-caps text-zinc-500">Текст подписи</label>
                <button onClick={insertLink} className="text-xs text-[#0055FF] flex items-center gap-1 hover:underline" data-testid="signature-insert-link">
                  <Link2 className="h-3 w-3" /> вставить ссылку
                </button>
              </div>
              <Textarea value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                rows={6} placeholder={"Больше с ней в 👉 [Частные сливы](https://t.me/...)\n[По домам 18+](https://t.me/...)"}
                className="rounded-none font-mono text-sm" data-testid="signature-content" />
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" onClick={() => setEditing(null)} className="rounded-none border-zinc-200" data-testid="signature-cancel">Отмена</Button>
              <Button onClick={save} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="signature-save">
                <Save className="h-4 w-4 mr-2" /> Сохранить
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 py-1">
            <Button onClick={() => setEditing({ name: "", content: "" })} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white w-full" data-testid="signature-new">
              <Plus className="h-4 w-4 mr-2" /> Новая подпись
            </Button>
            {items.length === 0 ? (
              <div className="text-sm text-zinc-400 border border-dashed border-zinc-200 p-6 text-center">Пока нет подписей</div>
            ) : (
              <div className="space-y-2" data-testid="signatures-list">
                {items.map((s) => (
                  <div key={s.id} className="border border-zinc-200 p-3" data-testid={`signature-item-${s.id}`}>
                    <div className="flex items-center justify-between">
                      <div className="font-semibold text-sm">{s.name}</div>
                      <div className="flex items-center gap-1">
                        <button onClick={() => setEditing(s)} className="p-1 text-zinc-400 hover:text-[#0055FF]" data-testid={`signature-edit-${s.id}`}><Pencil className="h-4 w-4" /></button>
                        <button onClick={() => remove(s.id)} className="p-1 text-zinc-400 hover:text-[#FF3333]" data-testid={`signature-delete-${s.id}`}><Trash2 className="h-4 w-4" /></button>
                      </div>
                    </div>
                    <pre className="text-xs text-zinc-500 mt-1 whitespace-pre-wrap font-sans line-clamp-3">{s.content}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
