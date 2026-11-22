import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { Search } from "lucide-react";

export interface PaletteItem {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  disabled?: boolean;
  run: () => void;
}

export default function CommandPalette({ items, onClose }: { items: PaletteItem[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  const visible = useMemo(() => {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((item) => {
      const haystack = `${item.label} ${item.hint ?? ""} ${item.group}`.toLowerCase();
      return terms.every((term) => haystack.includes(term));
    });
  }, [items, query]);

  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>("[data-active='true']")?.scrollIntoView({ block: "nearest" });
  }, [index, visible]);

  const choose = (item: PaletteItem | undefined) => {
    if (!item || item.disabled) return;
    onClose();
    item.run();
  };

  let lastGroup = "";
  return (
    <div className="overlay top" onMouseDown={onClose}>
      <motion.div className="dialog palette" role="dialog" aria-modal="true" aria-label="Palette de commandes"
        onMouseDown={(event) => event.stopPropagation()}
        initial={{ opacity: 0, y: -8, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.14 }}>
        <label className="palette-input">
          <Search size={16} />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="Chercher une action, une conversation, un projet…"
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") { event.preventDefault(); setIndex((value) => Math.min(visible.length - 1, value + 1)); }
              else if (event.key === "ArrowUp") { event.preventDefault(); setIndex((value) => Math.max(0, value - 1)); }
              else if (event.key === "Enter") { event.preventDefault(); choose(visible[index]); }
            }} />
          <kbd>Échap</kbd>
        </label>
        <div className="palette-list" ref={listRef}>
          {visible.length === 0 && <div className="palette-empty">Aucun résultat</div>}
          {visible.map((item, position) => {
            const header = item.group !== lastGroup ? <div className="palette-group" key={"g-" + item.group}>{item.group}</div> : null;
            lastGroup = item.group;
            return (
              <div key={item.id} style={{ display: "contents" }}>
                {header}
                <button type="button" data-active={position === index} disabled={item.disabled}
                  className={position === index ? "palette-item active" : "palette-item"}
                  onMouseEnter={() => setIndex(position)} onClick={() => choose(item)}>
                  {item.icon}<span>{item.label}</span>{item.hint && <small>{item.hint}</small>}
                </button>
              </div>
            );
          })}
        </div>
      </motion.div>
    </div>
  );
}
