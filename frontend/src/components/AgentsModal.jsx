import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import MultiSelectDropdown from './MultiSelectDropdown';
import './AgentsModal.css';

function emptyAgent() {
  return {
    name: '',
    model_spec: '',
    enabled: true,
    persona: '',
    influence_weight: 1.0,
    seniority_years: 0,
    kb_doc_ids: [],
    kb_categories: [],
    graph_id: '',
  };
}

export default function AgentsModal({ open, onClose, onChanged }) {
  const [agents, setAgents] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [kbDocs, setKbDocs] = useState([]);
  const [kgGraphs, setKgGraphs] = useState([]);
  const [kgError, setKgError] = useState('');
  const [isGeneratingPersona, setIsGeneratingPersona] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState(emptyAgent());

  const isEditing = useMemo(() => Boolean(editingId), [editingId]);
  const existingCategories = useMemo(() => {
    const set = new Set();
    for (const d of kbDocs || []) {
      for (const c of d?.categories || []) {
        if (typeof c === 'string' && c.trim()) set.add(c.trim());
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [kbDocs]);

  async function reload() {
    setIsLoading(true);
    setError('');
    try {
      const [items, docs, graphsRes] = await Promise.all([api.listAgents(), api.listKBDocuments(), api.listKGGraphs().catch((e) => ({ __error: e }))]);
      setAgents(items);
      setKbDocs(docs?.documents || []);
      if (graphsRes && graphsRes.__error) {
        setKgGraphs([]);
        setKgError(graphsRes.__error?.message || '加载图谱列表失败');
      } else {
        setKgGraphs(graphsRes?.graphs || []);
        setKgError('');
      }
    } catch (e) {
      setError(e?.message || '加载失败');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    Promise.resolve()
      .then(() => {
        if (cancelled) return;
        return reload();
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open]);

  function startCreate() {
    setEditingId(null);
    setDraft(emptyAgent());
  }

  function startEdit(agent) {
    setEditingId(agent.id);
    setDraft({
      name: agent.name || '',
      model_spec: agent.model_spec || '',
      enabled: Boolean(agent.enabled),
      persona: agent.persona || '',
      influence_weight: Number(agent.influence_weight ?? 1.0),
      seniority_years: Number(agent.seniority_years ?? 0),
      kb_doc_ids: Array.isArray(agent.kb_doc_ids) ? agent.kb_doc_ids : [],
      kb_categories: Array.isArray(agent.kb_categories) ? agent.kb_categories : [],
      graph_id: agent.graph_id || '',
    });
  }

  async function save() {
    setError('');
    try {
      if (!draft.name.trim() || !draft.model_spec.trim()) {
        setError('name 和 model_spec 不能为空');
        return;
      }
      if (isEditing) {
        await api.updateAgent(editingId, draft);
      } else {
        await api.createAgent(draft);
      }
      await reload();
      onChanged?.();
      startCreate();
    } catch (e) {
      setError(e?.message || '保存失败');
    }
  }

  async function remove(agentId) {
    if (!confirm('确定删除这个 Agent 吗？')) return;
    setError('');
    try {
      await api.deleteAgent(agentId);
      await reload();
      onChanged?.();
      if (editingId === agentId) startCreate();
    } catch (e) {
      setError(e?.message || '删除失败');
    }
  }

  async function generatePersona() {
    setError('');
    const name = (draft.name || '').trim();
    if (!name) {
      setError('请先填写名称');
      return;
    }
    setIsGeneratingPersona(true);
    try {
      const res = await api.generateAgentPersona({ name });
      const persona = res?.persona || '';
      if (!persona.trim()) {
        setError('生成人设失败：未返回内容');
        return;
      }
      setDraft((p) => ({ ...p, persona }));
    } catch (e) {
      setError(e?.message || '生成人设失败');
    } finally {
      setIsGeneratingPersona(false);
    }
  }

  const kgGraphOptions = useMemo(() => {
    const map = new Map();
    for (const g of kgGraphs || []) {
      const id = g?.graph_id;
      if (!id) continue;
      const name = g?.name || '图谱';
      map.set(id, { graph_id: id, label: `${name} · ${id}` });
    }
    const current = (draft.graph_id || '').trim();
    if (current && !map.has(current)) {
      map.set(current, { graph_id: current, label: `（当前）${current}` });
    }
    return Array.from(map.values());
  }, [kgGraphs, draft.graph_id]);

  if (!open) return null;

  return (
    <div className="agents-modal-overlay" onMouseDown={onClose}>
      <div className="agents-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="agents-modal-header">
          <div className="agents-modal-title">Agent 管理</div>
          <button className="agents-modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="agents-modal-body">
          <div className="agents-grid">
            <div className="agents-list">
              <div className="agents-list-header">
                <button className="btn" onClick={startCreate}>
                  + 新增 Agent
                </button>
                <button className="btn secondary" onClick={reload} disabled={isLoading}>
                  刷新
                </button>
                <div className="hint" style={{ marginTop: 0 }}>
                  共 {agents.length} 个
                </div>
              </div>

              {isLoading ? (
                <div className="hint">加载中...</div>
              ) : (
                agents.map((a) => (
                  <div key={a.id} className={`agent-row ${editingId === a.id ? 'active' : ''}`}>
                    <div className="agent-row-main" onClick={() => startEdit(a)}>
                      <div className="agent-row-title">
                        {a.enabled ? '' : '[停用] '}
                        {a.name}
                      </div>
                      <div className="agent-row-sub">{a.model_spec}</div>
                    </div>
                    <button className="btn danger small" onClick={() => remove(a.id)}>
                      删除
                    </button>
                  </div>
                ))
              )}
            </div>

            <div className="agents-editor">
              <div className="editor-title">{isEditing ? '编辑 Agent' : '新增 Agent'}</div>
              {error && <div className="error">{error}</div>}

              <label className="field">
                <div className="label">名称</div>
                <input
                  value={draft.name}
                  onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
                  placeholder="例如：资深架构师"
                />
              </label>

              <label className="field">
                <div className="label">model_spec</div>
                <input
                  value={draft.model_spec}
                  onChange={(e) => setDraft((p) => ({ ...p, model_spec: e.target.value }))}
                  placeholder="例如：dashscope:qwen-plus / ollama:llama3.1"
                />
              </label>

              <label className="field inline">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(e) => setDraft((p) => ({ ...p, enabled: e.target.checked }))}
                />
                <div className="label">启用</div>
              </label>

              <div className="field-row">
                <label className="field">
                  <div className="label">重要性权重</div>
                  <input
                    type="number"
                    step="0.1"
                    value={draft.influence_weight}
                    onChange={(e) =>
                      setDraft((p) => ({ ...p, influence_weight: Number(e.target.value) }))
                    }
                  />
                </label>
                <label className="field">
                  <div className="label">年资</div>
                  <input
                    type="number"
                    step="1"
                    value={draft.seniority_years}
                    onChange={(e) =>
                      setDraft((p) => ({ ...p, seniority_years: Number(e.target.value) }))
                    }
                  />
                </label>
              </div>

              <label className="field">
                <div className="label-row">
                  <div className="label">人设 / System Prompt</div>
                  <button
                    className="btn small secondary"
                    type="button"
                    onClick={generatePersona}
                    disabled={isLoading || isGeneratingPersona || !draft.name.trim()}
                    title="根据名称调用大模型自动生成一段可直接作为 system prompt 的人设"
                  >
                    {isGeneratingPersona ? '生成中...' : '自动生成'}
                  </button>
                </div>
                <textarea
                  rows={8}
                  value={draft.persona}
                  onChange={(e) => setDraft((p) => ({ ...p, persona: e.target.value }))}
                  placeholder="例如：你是一位经验丰富的安全工程师..."
                />
              </label>

              <label className="field">
                <div className="label">知识库文档 IDs（逗号分隔，可选）</div>
                <input
                  value={(draft.kb_doc_ids || []).join(',')}
                  onChange={(e) =>
                    setDraft((p) => ({
                      ...p,
                      kb_doc_ids: e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean),
                    }))
                  }
                  placeholder="例如：doc1,doc2"
                />
              </label>

              <label className="field">
                <MultiSelectDropdown
                  label="知识库分类（可多选，可新建）"
                  options={existingCategories}
                  value={draft.kb_categories || []}
                  onChange={(vals) => setDraft((p) => ({ ...p, kb_categories: vals }))}
                  placeholder="选择分类..."
                  createPlaceholder="新建分类（回车添加）"
                />
                <div className="hint" style={{ marginTop: 6 }}>
                  规则：若填写了 `kb_doc_ids` 则优先生效；否则会按分类过滤该专家可检索的知识库文档。
                </div>
              </label>

              <label className="field">
                <div className="label">Neo4j 图谱 graph_id（可选）</div>
                <select
                  className="select"
                  value={(draft.graph_id || '').trim()}
                  onChange={(e) => setDraft((p) => ({ ...p, graph_id: e.target.value }))}
                  disabled={isLoading}
                >
                  <option value="">（不绑定）</option>
                  {kgGraphOptions.map((o) => (
                    <option key={o.graph_id} value={o.graph_id}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {kgError ? (
                  <div className="hint" style={{ marginTop: 6 }}>
                    {kgError}（Neo4j 未配置/不可用时将无法加载列表）
                  </div>
                ) : null}
              </label>

              <div className="editor-actions">
                <button className="btn primary" onClick={save}>
                  保存
                </button>
                <button className="btn secondary" onClick={onClose}>
                  关闭
                </button>
              </div>
              <div className="hint">
                说明：权重和年资会影响 Stage2 的投票权重，并会在 Stage3 提示中展示给 Chairman。
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
