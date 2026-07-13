import { Bold, Italic, Link2, Heading1, Heading2, Quote } from "lucide-react";

const BTN = "h-8 w-8 flex items-center justify-center border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 transition-colors duration-150";

export function MarkdownToolbar({ textareaRef, value, onChange }) {
  const apply = (before, after = "", linePrefix = false) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const sel = value.slice(start, end);
    let next;
    let caret;
    if (linePrefix) {
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      next = value.slice(0, lineStart) + before + value.slice(lineStart);
      caret = end + before.length;
    } else {
      const inner = sel || "текст";
      next = value.slice(0, start) + before + inner + after + value.slice(end);
      caret = start + before.length + inner.length + after.length;
    }
    onChange(next);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(caret, caret);
    });
  };

  return (
    <div className="flex items-center gap-1 mb-2" data-testid="markdown-toolbar">
      <button type="button" onClick={() => apply("**", "**")} className={BTN} title="Жирный" data-testid="md-bold"><Bold className="h-4 w-4" /></button>
      <button type="button" onClick={() => apply("*", "*")} className={BTN} title="Курсив" data-testid="md-italic"><Italic className="h-4 w-4" /></button>
      <button type="button" onClick={() => apply("[", "](https://)")} className={BTN} title="Ссылка" data-testid="md-link"><Link2 className="h-4 w-4" /></button>
      <button type="button" onClick={() => apply("# ", "", true)} className={BTN} title="Заголовок" data-testid="md-h1"><Heading1 className="h-4 w-4" /></button>
      <button type="button" onClick={() => apply("## ", "", true)} className={BTN} title="Подзаголовок" data-testid="md-h2"><Heading2 className="h-4 w-4" /></button>
      <button type="button" onClick={() => apply("> ", "", true)} className={BTN} title="Цитата" data-testid="md-quote"><Quote className="h-4 w-4" /></button>
    </div>
  );
}
