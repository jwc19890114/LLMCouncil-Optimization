import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import MultiSelectDropdown from './MultiSelectDropdown';
import './KnowledgeBasePage.css';

function fileStem(name) {
  const n = (name || '').trim();
  if (!n) return '';
  const i = n.lastIndexOf('.');
  if (i <= 0) return n;
  return n.slice(0, i);
}

function inferTitle({ filename, text, isMarkdown }) {
  const fallback = fileStem(filename) || '未命名文档';
  const content = (text || '').trim();
  if (!content) return fallback;

  if (isMarkdown) {
    const m = content.match(/^#{1,2}\s+(.+)$/m);
    if (m?.[1]) return m[1].trim().slice(0, 80);
  }

  const firstLine = content.split(/\r?\n/).map((l) => l.trim()).find((l) => l.length > 0);
  if (firstLine) return firstLine.slice(0, 80);
  return fallback;
}

function isMarkdownFile(filename) {
  const n = (filename || '').toLowerCase();
  return n.endsWith('.md') || n.endsWith('.markdown');
}

export default function KnowledgeBasePage({ onBack }) {
  const [docs, setDocs] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedAgentIds, setSelectedAgentIds] = useState(new Set());
  const [categories, setCategories] = useState([]);
  const [batchItems, setBatchItems] = useState([]); // [{ filename, isMarkdown, title, source, text, size }]
  const [filename, setFilename] = useState('');
  const [isMarkdown, setIsMarkdown] = useState(false);
  const [title, setTitle] = useState('');
  const [source, setSource] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPreview, setShowPreview] = useState(true);
  const [editingDocId, setEditingDocId] = useState(null);
  const [editingDocCategories, setEditingDocCategories] = useState([]);

  const enabledAgents = useMemo(() => agents.filter((a) => a.enabled), [agents]);
  const isBatch = useMemo(() => Array.isArray(batchItems) && batchItems.length > 0, [batchItems]);
  const existingCategories = useMemo(() => {
    const set = new Set();
    for (const d of docs || []) {
      for (const c of d?.categories || []) {
        if (typeof c === 'string' && c.trim()) set.add(c.trim());
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [docs]);

  async function reload() {
    setIsLoading(true);
    setError('');
    try {
      const [d, a] = await Promise.all([api.listKBDocuments(), api.listAgents()]);
      setDocs(d.documents || []);
      setAgents(a || []);
    } catch (e) {
      setError(e?.message || '加载失败');
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => reload())
      .catch(() => {});
    return () => {
      cancelled = true;
      void cancelled;
    };
  }, []);

  function toggleAgent(id) {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function saveDocCategories(docId) {
    setError('');
    setIsLoading(true);
    try {
      await api.updateKBDocument(docId, { categories: editingDocCategories });
      setEditingDocId(null);
      setEditingDocCategories([]);
      await reload();
    } catch (e) {
      setError(e?.message || '更新分类失败');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleFiles(files) {
    setError('');
    const picked = Array.from(files || []).filter(Boolean);
    if (picked.length === 0) return;

    if (picked.length > 1) {
      setIsLoading(true);
      try {
        const items = [];
        for (const f of picked) {
          const name = f.name || '';
          const md = isMarkdownFile(name);
          if (f.size > 8 * 1024 * 1024) {
            setError('包含超大文件（>8MB），建议拆分后上传以提升检索与抽取效果。');
          }
          const content = await f.text();
          items.push({
            filename: name,
            isMarkdown: md,
            title: inferTitle({ filename: name, text: content, isMarkdown: md }),
            source: name,
            text: content,
            size: f.size,
          });
        }
        setBatchItems(items);
        setFilename('');
        setIsMarkdown(false);
        setTitle('');
        setSource('');
        setText('');
        setShowPreview(false);
      } catch (e) {
        setError(e?.message || '读取文件失败');
      } finally {
        setIsLoading(false);
      }
      return;
    }

    const f = picked[0];

    const name = f.name || '';
    const md = isMarkdownFile(name);
    setBatchItems([]);
    setFilename(name);
    setIsMarkdown(md);
    setSource(name);

    if (f.size > 8 * 1024 * 1024) {
      setError('文件过大（>8MB），建议拆分后上传以提升检索与抽取效果。');
    }

    try {
      const content = await f.text();
      setText(content);
      setTitle(inferTitle({ filename: name, text: content, isMarkdown: md }));
    } catch (e) {
      setError(e?.message || '读取文件失败');
    }
  }

  async function saveDoc() {
    setError('');
    if (!title.trim() || !text.trim()) {
      setError('标题和内容不能为空');
      return;
    }
    setIsLoading(true);
    try {
      await api.addKBDocument({
        title,
        source,
        text,
        categories,
        agent_ids: Array.from(selectedAgentIds),
      });
      setFilename('');
      setIsMarkdown(false);
      setTitle('');
      setSource('');
      setText('');
      setCategories([]);
      setSelectedAgentIds(new Set());
      await reload();
    } catch (e) {
      setError(e?.message || '保存失败');
    } finally {
      setIsLoading(false);
    }
  }

  function updateBatchTitle(index, nextTitle) {
    setBatchItems((prev) => {
      const list = Array.isArray(prev) ? [...prev] : [];
      if (!list[index]) return prev;
      list[index] = { ...list[index], title: nextTitle };
      return list;
    });
  }

  function removeBatchItem(index) {
    setBatchItems((prev) => {
      const list = Array.isArray(prev) ? [...prev] : [];
      list.splice(index, 1);
      return list;
    });
  }

  async function saveBatch() {
    setError('');
    const items = Array.isArray(batchItems) ? batchItems : [];
    if (items.length === 0) {
      setError('未选择文件');
      return;
    }

    setIsLoading(true);
    try {
      const documents = items.map((it) => ({
        title: (it.title || '').trim() || fileStem(it.filename) || '未命名文档',
        source: it.source || it.filename || '',
        text: it.text || '',
        categories,
        agent_ids: Array.from(selectedAgentIds),
      }));
      const resp = await api.addKBDocumentsBatch({ documents });
      const okCount = (resp?.results || []).filter((r) => r?.ok).length;
      const failCount = (resp?.results || []).filter((r) => !r?.ok).length;
      if (failCount > 0) {
        setError(`批量入库完成：成功 ${okCount}，失败 ${failCount}（可打开控制台查看详细返回）`);
        console.log('KB batch response:', resp);
      } else {
        alert(`批量入库完成：成功 ${okCount}`);
      }
      setBatchItems([]);
      setCategories([]);
      setSelectedAgentIds(new Set());
      await reload();
    } catch (e) {
      setError(e?.message || '批量保存失败');
    } finally {
      setIsLoading(false);
    }
  }

  async function remove(docId) {
    if (!confirm('确定删除这条知识库文档吗？')) return;
    setError('');
    setIsLoading(true);
    try {
      await api.deleteKBDocument(docId);
      await reload();
    } catch (e) {
      setError(e?.message || '删除失败');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="kbpage">
      <div className="kbpage-toolbar">
        <div className="kbpage-toolbar-left">
          <div className="kbpage-title">知识库上传</div>
          <div className="kbpage-subtitle">支持解析 .txt / .md，并自动生成标题与预览</div>
        </div>
        <div className="kbpage-toolbar-right">
          <button className="kbpage-btn" onClick={reload} disabled={isLoading}>
            刷新
          </button>
          <button className="kbpage-btn secondary" onClick={onBack}>
            返回聊天
          </button>
        </div>
      </div>

      <div className="kbpage-body">
        <div className="kbpage-grid">
          <div className="kbpage-panel">
            <div className="kbpage-panel-header">
              <div className="kbpage-panel-title">文档（{docs.length}）</div>
            </div>
            {isLoading ? (
              <div className="kbpage-hint">加载中...</div>
            ) : docs.length === 0 ? (
              <div className="kbpage-hint">暂无文档</div>
            ) : (
              <div className="kbpage-docs">
                  {docs.map((d) => (
                    <div key={d.id} className="kbpage-doc">
                      <div className="kbpage-doc-main">
                        <div className="kbpage-doc-title">{d.title}</div>
                        <div className="kbpage-doc-sub">
                          <span className="kbpage-doc-id">id: {d.id}</span>
                          {d.source ? <span> · {d.source}</span> : null}
                        </div>
                        {Array.isArray(d.categories) && d.categories.length > 0 && (
                          <div className="kbpage-doc-tags">分类：{d.categories.join('，')}</div>
                        )}
                        {Array.isArray(d.agent_ids) && d.agent_ids.length > 0 && (
                          <div className="kbpage-doc-tags">绑定：{d.agent_ids.length} 位专家</div>
                        )}
                        {editingDocId === d.id && (
                          <div className="kbpage-inline-editor">
                            <MultiSelectDropdown
                              options={existingCategories}
                              value={editingDocCategories}
                              onChange={setEditingDocCategories}
                              placeholder="选择分类..."
                              createPlaceholder="新建分类（回车添加）"
                            />
                            <div className="kbpage-inline-actions">
                              <button
                                className="kbpage-btn primary"
                                onClick={() => saveDocCategories(d.id)}
                                disabled={isLoading}
                              >
                                保存分类
                              </button>
                              <button
                                className="kbpage-btn secondary"
                                onClick={() => {
                                  setEditingDocId(null);
                                  setEditingDocCategories([]);
                                }}
                                disabled={isLoading}
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                      <div className="kbpage-doc-actions">
                        <button
                          className="kbpage-btn"
                          onClick={() => {
                            setEditingDocId((p) => (p === d.id ? null : d.id));
                            setEditingDocCategories(Array.isArray(d.categories) ? d.categories : []);
                          }}
                          disabled={isLoading}
                        >
                          分类
                        </button>
                        <button className="kbpage-btn danger" onClick={() => remove(d.id)} disabled={isLoading}>
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

          <div className="kbpage-panel">
            <div className="kbpage-panel-header">
              <div className="kbpage-panel-title">上传 / 解析</div>
              <div className="kbpage-panel-actions">
                <label className="kbpage-filebtn">
                  选择文件
                  <input
                    type="file"
                    multiple
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    onChange={(e) => handleFiles(e.target.files)}
                  />
                </label>
                <button
                  className="kbpage-btn secondary"
                  onClick={() => setShowPreview((v) => !v)}
                  disabled={!text || isBatch}
                >
                  {showPreview ? '隐藏预览' : '显示预览'}
                </button>
              </div>
            </div>

            <div
              className="kbpage-dropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                handleFiles(e.dataTransfer.files);
              }}
            >
              <div className="kbpage-dropzone-title">
                拖拽上传（.txt / .md）
                {isBatch ? `：已选择 ${batchItems.length} 个文件` : filename ? `：${filename}` : ''}
              </div>
              <div className="kbpage-dropzone-hint">
                提示：为获得更好的检索与图谱抽取效果，建议每篇文档主题单一、长度适中。
              </div>
            </div>

            {error && <div className="kbpage-error">{error}</div>}

            {isBatch && (
              <div className="kbpage-batch">
                <div className="kbpage-hint">批量入库：将按文件分别创建知识库文档（可在此编辑标题）。</div>
                <div className="kbpage-batch-list">
                  {batchItems.map((it, idx) => (
                    <div key={`${it.filename}-${idx}`} className="kbpage-batch-item">
                      <div className="kbpage-batch-name">{it.filename || `文件${idx + 1}`}</div>
                      <input
                        className="kbpage-batch-title"
                        value={it.title || ''}
                        onChange={(e) => updateBatchTitle(idx, e.target.value)}
                        placeholder="标题"
                      />
                      <button
                        type="button"
                        className="kbpage-btn danger"
                        onClick={() => removeBatchItem(idx)}
                        disabled={isLoading}
                      >
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="kbpage-form">
              <label className="kbpage-field">
                <div className="kbpage-label">标题</div>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={isBatch ? '批量模式下不使用此字段' : '自动解析，可编辑'}
                  disabled={isBatch}
                />
              </label>

              <label className="kbpage-field">
                <div className="kbpage-label">来源（可选）</div>
                <input
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  placeholder="例如：文件名 / 网址 / 内部编号"
                  disabled={isBatch}
                />
              </label>

              <div className="kbpage-field">
                <div className="kbpage-label">绑定专家（可选）</div>
                <div className="kbpage-agent-pills">
                  {enabledAgents.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      className={`kbpage-pill ${selectedAgentIds.has(a.id) ? 'on' : ''}`}
                      onClick={() => toggleAgent(a.id)}
                      title={a.model_spec}
                    >
                      {a.name}
                    </button>
                  ))}
                </div>
                <div className="kbpage-hint">
                  不绑定任何专家 = 默认不自动注入；你也可以在 Agent 管理中手动填 `kb_doc_ids`。
                </div>
              </div>

              <div className="kbpage-field">
                <MultiSelectDropdown
                  label="分类（可多选）"
                  options={existingCategories}
                  value={categories}
                  onChange={setCategories}
                  placeholder="选择分类..."
                  createPlaceholder="新建分类（回车添加）"
                />
                <div className="kbpage-hint">
                  说明：专家可配置 `kb_categories` 作为允许列表；该专家检索时会只在这些分类下的文档中查找。
                </div>
              </div>

              <div className="kbpage-split">
                <div className="kbpage-split-left">
                  <div className="kbpage-label">内容（可编辑）</div>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={12}
                    disabled={isBatch}
                    placeholder={isBatch ? '批量模式下不在此编辑内容（按文件入库）' : ''}
                  />
                </div>
                <div className="kbpage-split-right">
                  <div className="kbpage-label">预览</div>
                  <div className="kbpage-preview">
                    {!showPreview ? (
                      <div className="kbpage-hint">预览已关闭</div>
                    ) : !text || isBatch ? (
                      <div className="kbpage-hint">上传文件或粘贴内容后显示预览</div>
                    ) : isMarkdown ? (
                      <ReactMarkdown>{text}</ReactMarkdown>
                    ) : (
                      <pre className="kbpage-pre">{text}</pre>
                    )}
                  </div>
                </div>
              </div>

              <div className="kbpage-actions">
                {isBatch ? (
                  <button className="kbpage-btn primary" onClick={saveBatch} disabled={isLoading || batchItems.length === 0}>
                    批量保存（{batchItems.length}）
                  </button>
                ) : (
                  <button className="kbpage-btn primary" onClick={saveDoc} disabled={isLoading}>
                    保存到知识库
                  </button>
                )}
                <button
                  className="kbpage-btn secondary"
                  onClick={() => {
                    setBatchItems([]);
                    setFilename('');
                    setIsMarkdown(false);
                    setTitle('');
                    setSource('');
                    setText('');
                    setCategories([]);
                    setSelectedAgentIds(new Set());
                    setError('');
                  }}
                  disabled={isLoading}
                >
                  清空
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
