import { useEffect, useRef, useState } from "react";

/**
 * Checkbox dropdown. Native <select multiple> needs ctrl-click to pick more than
 * one and cannot show per-option counts, so this rolls the small amount of
 * behaviour it needs: click to toggle, click outside or Escape to close.
 *
 * options: [name, count][] — selected: Set — onChange(Set)
 */
export default function MultiSelect({ label, options, selected, onChange, renderOption }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    if (!open) return;
    const away = (e) => !box.current?.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const toggle = (name) => {
    const next = new Set(selected);
    next.has(name) ? next.delete(name) : next.add(name);
    onChange(next);
  };

  const summary =
    selected.size === 0
      ? "All"
      : selected.size === 1
        ? [...selected][0]
        : `${selected.size} selected`;

  return (
    <div className="ms" ref={box}>
      <button className={`ms-btn ${selected.size ? "active" : ""}`} onClick={() => setOpen((o) => !o)}>
        <span className="ms-label">{label}</span>
        <span className="ms-summary">{summary}</span>
        <span className="ms-caret">▾</span>
      </button>

      {open && (
        <div className="ms-menu">
          <div className="ms-actions">
            <button onClick={() => onChange(new Set(options.map(([n]) => n)))}>select all</button>
            <button onClick={() => onChange(new Set())} disabled={!selected.size}>clear</button>
          </div>
          <div className="ms-list">
            {options.map(([name, count]) => (
              <label key={name} className={selected.has(name) ? "on" : ""}>
                <input type="checkbox" checked={selected.has(name)} onChange={() => toggle(name)} />
                <span className="ms-name">{renderOption ? renderOption(name) : name}</span>
                <span className="ms-count">{count.toLocaleString()}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
