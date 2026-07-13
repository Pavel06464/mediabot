import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Bot, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { apiError } from "@/lib/api";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Вход выполнен");
      navigate("/");
    } catch (err) {
      toast.error(apiError(err.response?.data?.detail) || "Ошибка входа");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB] flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3 mb-8">
          <div className="h-11 w-11 bg-[#0055FF] flex items-center justify-center">
            <Bot className="h-6 w-6 text-white" strokeWidth={2.2} />
          </div>
          <div>
            <div className="text-lg font-black tracking-tighter leading-none">MEDIA POST BOT</div>
            <div className="label-caps text-zinc-400 mt-1">Telegraph Control Room</div>
          </div>
        </div>

        <div className="bg-white border border-zinc-200 p-8">
          <h1 className="text-2xl font-black tracking-tight mb-1">Вход</h1>
          <p className="text-sm text-zinc-500 mb-6">Войдите, чтобы управлять постами</p>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="label-caps text-zinc-500">Логин (email)</label>
              <Input
                data-testid="login-email"
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-none mt-1"
                placeholder="admin@mediabot.local"
                required
              />
            </div>
            <div>
              <label className="label-caps text-zinc-500">Пароль</label>
              <Input
                data-testid="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-none mt-1"
                placeholder="••••••••"
                required
              />
            </div>
            <Button
              data-testid="login-submit"
              type="submit"
              disabled={loading}
              className="w-full rounded-none bg-[#0055FF] hover:bg-[#0033CC] text-white"
            >
              <Lock className="h-4 w-4 mr-2" />
              {loading ? "Вход..." : "Войти"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
