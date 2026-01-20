import { useEffect, useState } from 'react';
import { api } from '../api';
import './SettingsModal.css';

function normalizeRounds(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 1;
  return Math.max(0, Math.min(3, Math.trunc(n)));
}

function normalizeAgentSearchResults(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 3;
  return Math.max(0, Math.min(10, Math.trunc(n)));
}

function normalizeIntervalSeconds(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 10;
  return Math.max(2, Math.min(3600, Math.trunc(n)));
}

function normalizeMaxFileMb(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 20;
  return Math.max(1, Math.min(500, Math.trunc(n)));
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
        enable_agent_web_search: Boolean(settings.enable_agent_web_search),
        agent_web_search_results: normalizeAgentSearchResults(settings.agent_web_search_results),
        enable_agent_auto_tools: Boolean(settings.enable_agent_auto_tools),
        enable_report_generation: Boolean(settings.enable_report_generation),
        report_instructions: String(settings.report_instructions || ''),
        auto_save_report_to_kb: Boolean(settings.auto_save_report_to_kb),
        auto_bind_report_to_conversation: Boolean(settings.auto_bind_report_to_conversation),
        report_kb_category: String(settings.report_kb_category || ''),
        kb_watch_enable: Boolean(settings.kb_watch_enable),
        kb_watch_roots: Array.isArray(settings.kb_watch_roots) ? settings.kb_watch_roots : [],
        kb_watch_exts: Array.isArray(settings.kb_watch_exts) ? settings.kb_watch_exts : [],
        kb_watch_interval_seconds: normalizeIntervalSeconds(settings.kb_watch_interval_seconds),
        kb_watch_max_file_mb: normalizeMaxFileMb(settings.kb_watch_max_file_mb),
        kb_watch_index_embeddings: Boolean(settings.kb_watch_index_embeddings),
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
                checked={Boolean(settings.enable_agent_web_search)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_agent_web_search: e.target.checked }))
                }
              />
              <span>允许每个 Agent 进行网页检索（每人一次）</span>
            </label>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.enable_agent_auto_tools)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_agent_auto_tools: e.target.checked }))
                }
              />
              <span>允许 Agent 自动触发后台工具（通过 ```tool JSON``` 请求）</span>
            </label>

            <div className="settings-row-inline">
              <div className="settings-label">每人条数</div>
              <select
                value={normalizeAgentSearchResults(settings.agent_web_search_results)}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    agent_web_search_results: normalizeAgentSearchResults(e.target.value),
                  }))
                }
                disabled={!settings.enable_agent_web_search}
              >
                <option value={0}>0</option>
                <option value={1}>1</option>
                <option value={2}>2</option>
                <option value={3}>3</option>
                <option value={5}>5</option>
                <option value={8}>8</option>
                <option value={10}>10</option>
              </select>
              <div className="settings-hint-inline">开启后会显著变慢，且可能触发 DDG 限流。</div>
            </div>

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

            <div className="settings-divider" />

            <div className="settings-section-title">知识库：持续导入</div>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.kb_watch_enable)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, kb_watch_enable: e.target.checked }))
                }
              />
              <span>开启文件夹监听：自动将新增/修改文件落盘到知识库</span>
            </label>

            <div className="settings-row-textarea">
              <div className="settings-label">监听目录（每行一个）</div>
              <textarea
                value={(settings.kb_watch_roots || []).join('\n')}
                onChange={(e) => {
                  const roots = String(e.target.value || '')
                    .split('\n')
                    .map((x) => x.trim())
                    .filter(Boolean);
                  setSettings((prev) => ({ ...prev, kb_watch_roots: roots }));
                }}
                rows={3}
                disabled={!settings.kb_watch_enable}
                placeholder="例如：data/kb_watch"
              />
            </div>

            <div className="settings-row-inline">
              <div className="settings-label">扩展名</div>
              <input
                value={(settings.kb_watch_exts || []).join(',')}
                onChange={(e) => {
                  const exts = String(e.target.value || '')
                    .split(',')
                    .map((x) => x.trim().replace(/^\./, '').toLowerCase())
                    .filter(Boolean);
                  setSettings((prev) => ({ ...prev, kb_watch_exts: exts }));
                }}
                disabled={!settings.kb_watch_enable}
              />
              <div className="settings-hint-inline">默认：txt,md（也可加 json/log）</div>
            </div>

            <div className="settings-row-inline">
              <div className="settings-label">扫描间隔（秒）</div>
              <input
                type="number"
                value={normalizeIntervalSeconds(settings.kb_watch_interval_seconds)}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    kb_watch_interval_seconds: normalizeIntervalSeconds(e.target.value),
                  }))
                }
                disabled={!settings.kb_watch_enable}
              />
              <div className="settings-hint-inline">更小更实时，但更耗资源</div>
            </div>

            <div className="settings-row-inline">
              <div className="settings-label">单文件上限（MB）</div>
              <input
                type="number"
                value={normalizeMaxFileMb(settings.kb_watch_max_file_mb)}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    kb_watch_max_file_mb: normalizeMaxFileMb(e.target.value),
                  }))
                }
                disabled={!settings.kb_watch_enable}
              />
              <div className="settings-hint-inline">避免误导入超大文件</div>
            </div>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.kb_watch_index_embeddings)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, kb_watch_index_embeddings: e.target.checked }))
                }
                disabled={!settings.kb_watch_enable}
              />
              <span>导入后自动建立 embedding（需要配置 KB_EMBEDDING_MODEL）</span>
            </label>

            <div className="settings-divider" />

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.enable_report_generation)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, enable_report_generation: e.target.checked }))
                }
              />
              <span>启用阶段 4：讨论结束后自动生成完整报告（Markdown）</span>
            </label>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.auto_save_report_to_kb)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, auto_save_report_to_kb: e.target.checked }))
                }
                disabled={!settings.enable_report_generation}
              />
              <span>自动将报告落盘到知识库（供小组复用）</span>
            </label>

            <label className="settings-row">
              <input
                type="checkbox"
                checked={Boolean(settings.auto_bind_report_to_conversation)}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, auto_bind_report_to_conversation: e.target.checked }))
                }
                disabled={!settings.enable_report_generation || !settings.auto_save_report_to_kb}
              />
              <span>落盘后自动绑定到当前会话（后续消息默认可检索）</span>
            </label>

            <div className="settings-row-inline">
              <div className="settings-label">报告分类</div>
              <input
                value={settings.report_kb_category || ''}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, report_kb_category: e.target.value }))
                }
                disabled={!settings.enable_report_generation || !settings.auto_save_report_to_kb}
              />
              <div className="settings-hint-inline">用于 KB 分类过滤，例如：council_reports</div>
            </div>

            <div className="settings-row-textarea">
              <div className="settings-label">报告模板</div>
              <textarea
                value={settings.report_instructions || ''}
                onChange={(e) =>
                  setSettings((prev) => ({ ...prev, report_instructions: e.target.value }))
                }
                rows={8}
                disabled={!settings.enable_report_generation}
                placeholder="作为阶段4报告的默认要求（Markdown 结构/章节/格式等）"
              />
            </div>

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
