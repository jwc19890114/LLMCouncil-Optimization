import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import './PluginsPage.css';

function safeJsonParse(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

export default function PluginsPage({ onBack }) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [plugins, setPlugins] = useState([]);
  const [tools, setTools] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [configDraft, setConfigDraft] = useState('');
  const [configError, setConfigError] = useState('');

  async function reload() {
    setIsLoading(true);
    setError('');
    try {
      const data = await api.listPlugins();
      setPlugins(data?.plugins || []);
      setTools(data?.tools || []);
    } catch (e) {
      setError(e?.message || '加载插件失败');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  const byName = useMemo(() => {
    const m = new Map();
    for (const p of plugins || []) m.set(p.name, p);
    return m;
  }, [plugins]);

  return (
    <div className="plugins-page">
      <div className="plugins-header">
        <div className="plugins-title">插件管理</div>
        <div className="plugins-actions">
          <button className="plugins-btn" onClick={onBack}>
            返回聊天
          </button>
          <button
            className="plugins-btn"
            onClick={async () => {
              setIsLoading(true);
              setError('');
              try {
                const data = await api.reloadPlugins();
                setPlugins(data?.plugins || []);
                setTools(data?.tools || []);
              } catch (e) {
                setError(e?.message || '刷新失败');
              } finally {
                setIsLoading(false);
              }
            }}
            disabled={isLoading}
          >
            刷新
          </button>
        </div>
      </div>

      {error ? <div className="plugins-error">{error}</div> : null}

      <div className="plugins-hint">
        这里管理的是“后台工具（Tools）”。关闭后将无法创建对应类型的后台任务（Jobs）。
      </div>

      <div className="plugins-grid">
        {(plugins || []).map((p) => (
          <div key={p.name} className="plugin-card">
            <div className="plugin-top">
              <div className="plugin-main">
                <div className="plugin-name">{p.title || p.name}</div>
                <div className="plugin-key">{p.name}</div>
              </div>
              <label className="plugin-toggle">
                <input
                  type="checkbox"
                  checked={Boolean(p.enabled)}
                  disabled={Boolean(p.locked) || isLoading}
                  onChange={async (e) => {
                    const enabled = e.target.checked;
                    setIsLoading(true);
                    setError('');
                    try {
                      await api.patchPlugin(p.name, { enabled });
                      await reload();
                    } catch (err) {
                      setError(err?.message || '更新失败');
                    } finally {
                      setIsLoading(false);
                    }
                  }}
                />
                <span>{p.enabled ? '已启用' : '已禁用'}</span>
              </label>
            </div>
            {p.description ? <div className="plugin-desc">{p.description}</div> : null}
            <div className="plugin-footer">
              <button
                className="plugins-btn small"
                onClick={() => {
                  const next = expanded === p.name ? null : p.name;
                  setExpanded(next);
                  setConfigError('');
                  setConfigDraft(JSON.stringify((p.config || {}), null, 2));
                }}
              >
                配置
              </button>
              <div className="plugin-tools">
                {tools.includes(p.name) ? <span className="plugin-badge">已注册</span> : <span className="plugin-badge off">未注册</span>}
              </div>
            </div>

            {expanded === p.name ? (
              <div className="plugin-config">
                {configError ? <div className="plugins-error">{configError}</div> : null}
                <textarea
                  value={configDraft}
                  onChange={(e) => setConfigDraft(e.target.value)}
                  rows={6}
                />
                <div className="plugin-config-actions">
                  <button
                    className="plugins-btn small"
                    onClick={() => {
                      setExpanded(null);
                      setConfigError('');
                    }}
                    disabled={isLoading}
                  >
                    关闭
                  </button>
                  <button
                    className="plugins-btn small primary"
                    onClick={async () => {
                      const parsed = safeJsonParse(configDraft || '');
                      if (!parsed.ok) {
                        setConfigError(`JSON 解析失败：${parsed.error}`);
                        return;
                      }
                      setIsLoading(true);
                      setConfigError('');
                      try {
                        await api.patchPlugin(p.name, { config: parsed.value || {} });
                        await reload();
                        setExpanded(null);
                      } catch (err) {
                        setConfigError(err?.message || '保存失败');
                      } finally {
                        setIsLoading(false);
                      }
                    }}
                    disabled={isLoading}
                  >
                    保存
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

