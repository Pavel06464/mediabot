import { useEffect, useState, useRef } from "react";
import { toast } from "sonner";
import { Droplets, Check, Upload } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import api, { apiError } from "@/lib/api";

const POSITIONS = [
  ["top-left", "top-center", "top-right"],
  ["middle-left", "center", "middle-right"],
  ["bottom-left", "bottom-center", "bottom-right"],
];

const DEFAULT = {
  enabled: false,
  type: "text",
  text: "@mychannel",
  color: "white",
  logo_b64: "",
  position: "bottom-right",
  size: 15,
  opacity: 50,
};

export default function WatermarkSettings({ open, onOpenChange }) {
  const [cfg, setCfg] = useState(DEFAULT);
  const [preview, setPreview] = useState("");
  const [saving, setSaving] = useState(false);
  const logoRef = useRef(null);

  useEffect(() => {
    if (open) {
      api.get("/settings/watermark").then((r) => setCfg({ ...DEFAULT, ...r.data })).catch(() => {});
    }
  }, [open]);

  // Live preview (debounced)
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      api
        .post("/settings/watermark/preview", { ...cfg, enabled: true })
        .then((r) => setPreview(r.data.image))
        .catch(() => {});
    }, 350);
    return () => clearTimeout(t);
  }, [cfg, open]);

  const up = (patch) => setCfg((c) => ({ ...c, ...patch }));

  const onLogo = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 800 * 1024) return toast.error("Логотип слишком большой (макс 800 КБ)");
    const reader = new FileReader();
    reader.onload = () => up({ logo_b64: reader.result, type: "logo" });
    reader.readAsDataURL(file);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/settings/watermark", cfg);
      toast.success(cfg.enabled ? "Водяной знак включён" : "Водяной знак сохранён");
      onOpenChange(false);
    } catch (err) {
      toast.error(apiError(err.response?.data?.detail) || "Ошибка");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none sm:max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="watermark-dialog">
        <DialogHeader>
          <DialogTitle className="text-xl font-black tracking-tight flex items-center gap-2">
            <Droplets className="h-5 w-5 text-[#0055FF]" /> Водяной знак
          </DialogTitle>
          <DialogDescription>
            Автоматически накладывается на все загружаемые фото. Настройте вид ниже.
          </DialogDescription>
        </DialogHeader>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Controls */}
          <div className="space-y-5">
            <div className="flex items-center justify-between border border-zinc-200 p-3">
              <span className="font-semibold text-sm">Включить водяной знак</span>
              <Switch checked={cfg.enabled} onCheckedChange={(v) => up({ enabled: v })} data-testid="wm-enabled" />
            </div>

            <Tabs value={cfg.type} onValueChange={(v) => up({ type: v })}>
              <TabsList className="rounded-none w-full">
                <TabsTrigger value="text" className="rounded-none flex-1" data-testid="wm-tab-text">Текст</TabsTrigger>
                <TabsTrigger value="logo" className="rounded-none flex-1" data-testid="wm-tab-logo">Логотип</TabsTrigger>
              </TabsList>
              <TabsContent value="text" className="space-y-3 pt-3">
                <div>
                  <label className="label-caps text-zinc-500">Текст</label>
                  <Input value={cfg.text} onChange={(e) => up({ text: e.target.value })} className="rounded-none mt-1" data-testid="wm-text" />
                </div>
                <div>
                  <label className="label-caps text-zinc-500">Цвет</label>
                  <div className="flex gap-2 mt-1">
                    {["white", "black"].map((c) => (
                      <button key={c} onClick={() => up({ color: c })}
                        className={`px-4 py-2 text-sm border ${cfg.color === c ? "border-[#0055FF] ring-2 ring-[#0055FF]/30" : "border-zinc-300"}`}
                        data-testid={`wm-color-${c}`}>
                        {c === "white" ? "Белый" : "Чёрный"}
                      </button>
                    ))}
                  </div>
                </div>
              </TabsContent>
              <TabsContent value="logo" className="space-y-3 pt-3">
                <input ref={logoRef} type="file" accept="image/png,image/webp" hidden onChange={onLogo} data-testid="wm-logo-input" />
                <Button variant="outline" onClick={() => logoRef.current?.click()} className="rounded-none w-full border-zinc-300" data-testid="wm-logo-btn">
                  <Upload className="h-4 w-4 mr-2" /> {cfg.logo_b64 ? "Заменить логотип" : "Загрузить логотип (PNG)"}
                </Button>
                <p className="text-xs text-zinc-400">Лучше PNG с прозрачным фоном, до 800 КБ.</p>
              </TabsContent>
            </Tabs>

            <div>
              <label className="label-caps text-zinc-500">Расположение</label>
              <div className="grid grid-cols-3 gap-1.5 mt-1 w-32">
                {POSITIONS.flat().map((p) => (
                  <button key={p} onClick={() => up({ position: p })}
                    className={`h-9 border transition-colors ${cfg.position === p ? "bg-[#0055FF] border-[#0055FF]" : "bg-zinc-50 border-zinc-300 hover:border-zinc-400"}`}
                    data-testid={`wm-pos-${p}`} title={p}>
                    <span className={`block w-1.5 h-1.5 mx-auto ${cfg.position === p ? "bg-white" : "bg-zinc-400"}`} />
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="flex justify-between label-caps text-zinc-500"><span>Размер</span><span>{cfg.size}%</span></div>
              <Slider value={[cfg.size]} min={3} max={60} step={1} onValueChange={(v) => up({ size: v[0] })} className="mt-2" data-testid="wm-size" />
            </div>
            <div>
              <div className="flex justify-between label-caps text-zinc-500"><span>Прозрачность</span><span>{cfg.opacity}%</span></div>
              <Slider value={[cfg.opacity]} min={5} max={100} step={5} onValueChange={(v) => up({ opacity: v[0] })} className="mt-2" data-testid="wm-opacity" />
            </div>
          </div>

          {/* Preview */}
          <div>
            <label className="label-caps text-zinc-500">Предпросмотр</label>
            <div className="mt-1 border border-zinc-200 bg-zinc-100 aspect-[8/5] flex items-center justify-center overflow-hidden">
              {preview ? (
                <img src={preview} alt="preview" className="w-full h-full object-cover" data-testid="wm-preview" />
              ) : (
                <span className="text-zinc-400 text-sm">Загрузка превью...</span>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-2">Так знак будет выглядеть на фото. Настройки применяются к новым загрузкам.</p>
          </div>
        </div>

        <Button onClick={save} disabled={saving} className="w-full rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white mt-2" data-testid="wm-save">
          <Check className="h-4 w-4 mr-2" /> {saving ? "Сохранение..." : "Сохранить"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
