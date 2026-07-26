import { useState } from "react";
import { X, Hash } from "lucide-react";

const clean = (raw) =>
  raw
    .split(/[\s,]+/)
    .map((t) => t.trim().replace(/^#+/, "").replace(/[^\wа-яёА-ЯЁ]/gu, ""))
    .filter(Boolean)
    .map((t) => "#" + t);

export function HashtagsInput({ tags, setTags }) {
  const [value, setValue] = useState("");

  const commit = (raw) => {
    const next = clean(raw);
    if (!next.length) return;
    setTags((prev) => {
      const seen = new Set(prev.map((t) => t.toLowerCase()));
      const merged = [...prev];
      next.forEach((t) => { if (!seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); merged.push(t); } });
      return merged;
    });
    setValue("");
  };

  const onKeyDown = (e) => {
    if (["Enter", ",", " "].includes(e.key)) { e.preventDefault(); commit(value); }
    else if (e.key === "Backspace" && !value && tags.length) setTags((prev) => prev.slice(0, -1));
  };

  return (
    <div className="border border-zinc-200 bg-white p-2 flex flex-wrap gap-2 items-center" data-testid="hashtags-input">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 bg-blue-50 text-[#0055FF] text-sm font-semibold px-2 py-1" data-testid={`hashtag-${t.slice(1)}`}>
          {t}
          <button type="button" onClick={() => setTags((prev) => prev.filter((x) => x !== t))} className="hover:text-[#FF3333]">
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <div className="flex items-center gap-1 flex-1 min-w-[140px]">
        <Hash className="h-4 w-4 text-zinc-400" />
        <input
          data-testid="hashtags-field"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => commit(value)}
          placeholder={tags.length ? "ещё тег…" : "теги через пробел или запятую"}
          className="flex-1 outline-none text-sm bg-transparent py-1"
        />
      </div>
    </div>
  );
}
