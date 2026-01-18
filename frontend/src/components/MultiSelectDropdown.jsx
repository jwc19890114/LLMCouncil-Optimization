import { useEffect, useMemo, useRef, useState } from 'react';
import './MultiSelectDropdown.css';

function norm(s) {
  return (s || '').trim();
}

export default function MultiSelectDropdown({
  label,
  options,
  value,
  onChange,
  placeholder = '选择...',
  allowCreate = true,
  createPlaceholder = '新建分类（回车添加）',
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const rootRef = useRef(null);

  const opts = useMemo(() => {
    const set = new Set();
    const out = [];
    for (const o of options || []) {
      const n = norm(o);
      if (!n || set.has(n)) continue;
      set.add(n);
      out.push(n);
    }
    out.sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
    return out;
  }, [options]);

  const selected = useMemo(() => {
    const set = new Set();
    const out = [];
    for (const v of value || []) {
      const n = norm(v);
      if (!n || set.has(n)) continue;
      set.add(n);
      out.push(n);
    }
    return out;
  }, [value]);

  const filtered = useMemo(() => {
    const q = norm(input).toLowerCase();
    if (!q) return opts;
    return opts.filter((o) => o.toLowerCase().includes(q));
  }, [opts, input]);

  useEffect(() => {
    function onDocDown(e) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onDocDown);
    return () => document.removeEventListener('mousedown', onDocDown);
  }, []);

  function toggleItem(item) {
    const n = norm(item);
    if (!n) return;
    const set = new Set(selected);
    if (set.has(n)) set.delete(n);
    else set.add(n);
    onChange(Array.from(set));
  }

  function addNew() {
    const n = norm(input);
    if (!n) return;
    if (!allowCreate) return;
    if (selected.includes(n)) {
      setInput('');
      return;
    }
    onChange([...selected, n]);
    setInput('');
  }

  const display = selected.length === 0 ? placeholder : selected.join('，');

  return (
    <div className="msd" ref={rootRef}>
      {label ? <div className="msd-label">{label}</div> : null}
      <button
        type="button"
        className={`msd-trigger ${disabled ? 'disabled' : ''}`}
        onClick={() => {
          if (disabled) return;
          setOpen((v) => !v);
        }}
      >
        <span className={`msd-trigger-text ${selected.length === 0 ? 'placeholder' : ''}`}>
          {display}
        </span>
        <span className="msd-caret">▾</span>
      </button>

      {open && (
        <div className="msd-popover">
          <div className="msd-search">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addNew();
                }
                if (e.key === 'Escape') setOpen(false);
              }}
              placeholder={allowCreate ? createPlaceholder : '搜索...'}
            />
            {allowCreate && (
              <button type="button" className="msd-btn" onClick={addNew} disabled={!norm(input)}>
                添加
              </button>
            )}
          </div>
          <div className="msd-list">
            {filtered.length === 0 ? (
              <div className="msd-empty">暂无可选项</div>
            ) : (
              filtered.map((o) => (
                <label key={o} className="msd-item">
                  <input
                    type="checkbox"
                    checked={selected.includes(o)}
                    onChange={() => toggleItem(o)}
                  />
                  <span>{o}</span>
                </label>
              ))
            )}
          </div>
          {selected.length > 0 && (
            <div className="msd-footer">
              <button
                type="button"
                className="msd-btn secondary"
                onClick={() => onChange([])}
              >
                清空
              </button>
              <button type="button" className="msd-btn" onClick={() => setOpen(false)}>
                完成
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

