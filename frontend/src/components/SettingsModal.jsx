import { useEffect, useState } from 'react';
import { api } from '../api';
import './SettingsModal.css';

function normalizeRounds(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 1;
  return Math.max(0, Math.min(3, Math.trunc(n)));
}

export default function SettingsModal({ open, onClose }) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setIsLoading(true);
    setError('');
    api
      .getSettings()
      .then((s) => {
        if (cancelled) return;
        setSettings(s);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || '加载设置失败');
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function save() {
    if (!settings) return;
    setIsLoading(true);
    setError('');
    try {
      const patch = {
        enable_preprocess: Boolean(settings.enable_preprocess),
        enable_roundtable: Boolean(settings.enable_roundtable),
        enable_fact_check: Boolean(settings.enable_fact_check),
        roundtable_rounds: normalizeRounds(settings.roundtable_rounds),
      };
      const resp = await api.patchSettings(patch);
      setSettings(resp?.settings || settings);
      onClose?.();
    } catch (e) {
      setError(e?.message || '保存失败');
    } finally {
      setIsLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-modal-header">
          <h2>流程设置</h2>
          <button className="settings-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {isLoading && !settings ? <div className="settings-hint">加载中...</div> : null}
        {error ? <div className="settings-error">{error}</div> : null}

        {settings ? (
          <div className="settings-form">
            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.enable_preprocess)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_preprocess: e.target.checked }))
                }
              />
              <span>启用阶段 0：发送前文档预处理（摘要/拆分/提问）</span>
            </label>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.enable_roundtable)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_roundtable: e.target.checked }))
                }
              />
              <span>启用阶段 2B：圆桌讨论（基于人设 + 网页信息）</span>
            </label>

            <div className="settings-row-inline">
              <div className="settings-label">圆桌轮数</div>
              <select
                value={normalizeRounds(settings.roundtable_rounds)}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    roundtable_rounds: normalizeRounds(e.target.value),
                  }))
                }
                disabled={!settings.enable_roundtable}
              >
                <option value={0}>0（关闭）</option>
                <option value={1}>1</option>
                <option value={2}>2</option>
                <option value={3}>3</option>
              </select>
              <div className="settings-hint-inline">建议 1~2 轮，轮数越多耗时越长。</div>
            </div>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.enable_fact_check)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_fact_check: e.target.checked }))
                }
              />
              <span>启用阶段 2C：事实核查（输出结构化 JSON）</span>
            </label>

            <div className="settings-actions">
              <button className="settings-btn secondary" onClick={onClose} disabled={isLoading}>
                取消
              </button>
              <button className="settings-btn primary" onClick={save} disabled={isLoading}>
                保存
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
