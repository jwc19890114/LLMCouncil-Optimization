import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import './ConversationAgentsModal.css';

export default function ConversationAgentsModal({
  onClose,
  conversationId,
  initialAgentIds,
  onSaved,
}) {
  const [agents, setAgents] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState('');

  const enabledAgents = useMemo(() => agents.filter((a) => a.enabled), [agents]);
  const filteredAgents = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) => {
      const name = (a.name || '').toLowerCase();
      const spec = (a.model_spec || '').toLowerCase();
      return name.includes(q) || spec.includes(q);
    });
  }, [agents, query]);

  useEffect(() => {
    let cancelled = false;
    api
      .listAgents()
      .then((items) => {
        if (cancelled) return;
        setAgents(items);
        const ids = Array.isArray(initialAgentIds) ? initialAgentIds : [];
        setSelected(new Set(ids));
        setError('');
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialAgentIds]);

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllEnabled() {
    setSelected(new Set(enabledAgents.map((a) => a.id)));
  }

  function useDefaultAllEnabled() {
    setSelected(new Set());
  }

  async function save() {
    if (!conversationId) return;
    setError('');
    try {
      const ids = Array.from(selected);
      await api.setConversationAgents(conversationId, ids);
      onSaved?.(ids);
      onClose();
    } catch (e) {
      setError(e?.message || '保存失败');
    }
  }

  return (
    <div className="conv-agents-overlay" onMouseDown={onClose}>
      <div className="conv-agents-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="conv-agents-header">
          <div className="conv-agents-title">
            选择本会话参与的专家
            <span className="conv-agents-subtitle">
              {selected.size === 0 ? '（默认：全部启用）' : `（已选：${selected.size}）`}
            </span>
          </div>
          <button className="conv-agents-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="conv-agents-body">
          <div className="conv-agents-topbar">
            <div className="conv-agents-hint">
              不选择任何专家 = 使用“专家库中所有启用的专家”（默认）。
            </div>
            <div className="conv-agents-search">
              <input
                className="conv-agents-search-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索专家（名称 / model_spec）..."
              />
            </div>
          </div>

          <div className="conv-agents-actions">
            <button className="conv-btn" onClick={selectAllEnabled} disabled={isLoading}>
              全选启用
            </button>
            <button className="conv-btn secondary" onClick={useDefaultAllEnabled} disabled={isLoading}>
              恢复默认
            </button>
          </div>

          {error && <div className="conv-error">{error}</div>}
          {isLoading ? (
            <div className="conv-agents-loading">加载中...</div>
          ) : (
            <div className="conv-agents-grid">
              {filteredAgents.map((a) => {
                const isChecked = selected.has(a.id);
                const initials = (a.name || '?').trim().slice(0, 1).toUpperCase();
                return (
                  <button
                    key={a.id}
                    className={`conv-agent-card ${isChecked ? 'checked' : ''} ${
                      a.enabled ? '' : 'disabled'
                    }`}
                    onClick={() => toggle(a.id)}
                    type="button"
                    title={a.model_spec}
                  >
                    <div className="conv-agent-top">
                      <div className="conv-agent-avatar">{initials}</div>
                      <div className={`conv-agent-check ${isChecked ? 'on' : ''}`}>
                        {isChecked ? '✓' : ''}
                      </div>
                    </div>
                    <div className="conv-agent-name">
                      {a.enabled ? '' : '[停用] '}
                      {a.name}
                    </div>
                    <div className="conv-agent-spec">{a.model_spec}</div>
                  </button>
                );
              })}
            </div>
          )}

          <div className="conv-agents-footer">
            <button className="conv-btn primary" onClick={save} disabled={!conversationId}>
              保存
            </button>
            <button className="conv-btn secondary" onClick={onClose}>
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
