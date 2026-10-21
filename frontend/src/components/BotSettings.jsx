import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Bot, RefreshCw, ShieldCheck } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api, { apiError } from "@/lib/api";

const SOURCE_LABEL = { db: "из настроек сайта", env: "из .env на сервере", none: "не задан" };

function StatusLine({ check }) {
  if (!check) return null;
  const map = {
    valid: "text-green-700 bg-green-50 border-green-200",
    invalid: "text-red-700 bg-red-50 border-red-200",
    network_error: "text-amber-700 bg-amber-50 border-amber-200",
    not_configured: "text-zinc-600 bg-zinc-50 border-zinc-200",
  };
  const title = {
    valid: "Токен рабочий",
    invalid: "Бот не найден / токен невалиден",
    network_error: "Нет связи с Telegram",
    not_configured: "Токен не задан",
  }[check.status];
  return (
    <div className={`border px-3 py-2 text-sm ${map[check.status] || map.not_configured}`} data-testid="bot-check-status">
      <div className="font-medium">{title}</div>
      {check.bot ? (
        <div>{check.bot.first_name} {check.bot.username ? `(@${check.bot.username})` : ""}</div>
      ) : (
        <div className="text-xs opacity-80">{check.message}</div>
      )}
    </div>
  );
}

export default function BotSettings({ open, onOpenChange }) {
  const [info, setInfo] = useState(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/settings/bot", { params: { check: true } });
      setInfo(data);
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    }
  }, []);

  useEffect(() => { if (open) { setToken(""); load(); } }, [open, load]);

  const run = async (fn) => {
    setBusy(true);
    try { await fn(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };

  const save = () => run(async () => {
    const { data } = await api.put("/settings/bot", { token: token.trim() || null });
    setInfo(data); setToken("");
    toast.success("Настройки бота сохранены");
  });

  const check = () => run(async () => {
    const { data } = await api.post("/settings/bot/check", { token: token.trim() || null });
    setInfo((prev) => ({ ...prev, check: data }));
  });

  const restart = () => run(async () => {
    const { data } = await api.post("/settings/bot/restart");
    setInfo(data);
    toast.success(data.polling_running ? "Бот перезапущен" : "Бот остановлен (polling выключен)");
  });

  const togglePolling = (v) => run(async () => {
    const { data } = await api.put("/settings/bot", { polling_enabled: v });
    setInfo(data);
  });

  const clearToken = () => run(async () => {
    const { data } = await api.put("/settings/bot", { clear_token: true });
    setInfo(data);
    toast.success("Токен удалён из настроек сайта");
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none max-w-lg" data-testid="bot-settings-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Bot className="h-5 w-5 text-[#0055FF]" /> Telegram-бот</DialogTitle>
          <DialogDescription>Токен бота и приём сообщений (polling). Применяется без перезапуска сервера.</DialogDescription>
        </DialogHeader>

        {info && (
          <div className="space-y-4">
            <div className="text-sm">
              <div>Текущий токен: <b>{info.token_masked || "—"}</b> <span className="text-zinc-500">({SOURCE_LABEL[info.source]})</span></div>
              <div>Polling: <b>{info.polling_running ? "работает" : "остановлен"}</b>
                {info.polling_error ? <span className="text-red-600"> — {info.polling_error}</span> : null}</div>
            </div>

            <StatusLine check={info.check} />

            <div className="space-y-2">
              <label className="text-sm font-medium">Новый токен</label>
              <Input
                type="password"
                autoComplete="off"
                placeholder="123456789:AA..."
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className="rounded-none"
                data-testid="bot-token-input"
              />
              <p className="text-xs text-zinc-500">Возьмите у @BotFather. Полностью токен больше нигде не показывается.</p>
            </div>

            <div className="flex items-center justify-between">
              <div className="text-sm">
                Принимать сообщения боту (polling)
                {info.polling_source === "env" ? <div className="text-xs text-zinc-500">сейчас по .env</div> : null}
              </div>
              <Switch checked={!!info.polling_enabled} onCheckedChange={togglePolling} disabled={busy} data-testid="bot-polling-switch" />
            </div>

            <div className="flex flex-wrap gap-2">
              <Button onClick={save} disabled={busy || !token.trim()} className="rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white" data-testid="bot-save-btn">Сохранить</Button>
              <Button onClick={check} disabled={busy} variant="outline" className="rounded-none" data-testid="bot-check-btn">
                <ShieldCheck className="h-4 w-4 mr-2" /> Проверить
              </Button>
              <Button onClick={restart} disabled={busy} variant="outline" className="rounded-none" data-testid="bot-restart-btn">
                <RefreshCw className="h-4 w-4 mr-2" /> Перезапустить бота
              </Button>
              {info.source === "db" && (
                <Button onClick={clearToken} disabled={busy} variant="ghost" className="rounded-none text-red-600" data-testid="bot-clear-btn">Удалить токен</Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
