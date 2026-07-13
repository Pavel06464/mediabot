import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Radio, Trash2, Check } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api, { apiError } from "@/lib/api";

export default function ChannelSettings({ open, onOpenChange, onChange }) {
  const [channel, setChannel] = useState(null);
  const [identifier, setIdentifier] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      api.get("/settings").then((r) => setChannel(r.data.channel_id ? r.data : null)).catch(() => {});
    }
  }, [open]);

  const save = async () => {
    if (!identifier.trim()) return toast.error("Укажите @username или ID канала");
    setSaving(true);
    try {
      const { data } = await api.post("/settings/channel", { identifier: identifier.trim() });
      setChannel(data);
      setIdentifier("");
      toast.success(`Канал сохранён: ${data.channel_title}`);
      onChange?.();
    } catch (err) {
      toast.error(apiError(err.response?.data?.detail) || "Ошибка");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api.delete("/settings/channel");
      setChannel(null);
      toast.success("Канал удалён");
      onChange?.();
    } catch {
      toast.error("Ошибка удаления");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none sm:max-w-md" data-testid="channel-dialog">
        <DialogHeader>
          <DialogTitle className="text-xl font-black tracking-tight flex items-center gap-2">
            <Radio className="h-5 w-5 text-[#0055FF]" /> Настройка канала
          </DialogTitle>
          <DialogDescription>
            Бот должен быть администратором канала с правом публикации.
          </DialogDescription>
        </DialogHeader>

        {channel && (
          <div className="border border-zinc-200 p-3 flex items-center justify-between bg-zinc-50">
            <div>
              <div className="font-semibold">{channel.channel_title}</div>
              <div className="text-xs text-zinc-500 font-mono">{channel.channel_id}</div>
            </div>
            <button onClick={remove} className="text-zinc-400 hover:text-[#FF3333]" data-testid="channel-remove">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        )}

        <div className="space-y-2">
          <label className="label-caps text-zinc-500">@username или ID канала</label>
          <Input
            data-testid="channel-input"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="@mychannel или -100123456789"
            className="rounded-none"
          />
          <Button
            onClick={save}
            disabled={saving}
            className="w-full rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white"
            data-testid="channel-save"
          >
            <Check className="h-4 w-4 mr-2" /> {saving ? "Проверка..." : "Сохранить канал"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
