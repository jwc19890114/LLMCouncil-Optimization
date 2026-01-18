import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import MultiSelectDropdown from './MultiSelectDropdown';
import './GraphPage.css';

export default function GraphPage({ onBack, initialGraphOptions }) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const cancelExtractRef = useRef(false);
  const resizeObserverRef = useRef(null);
  const resizingRef = useRef(false);
  const resizeStartRef = useRef({ clientX: 0, width: 420 });

  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(() => {
    const fallback = 420;
    try {
      const raw = localStorage.getItem('kg:leftPanelWidth');
      const parsed = Number.parseInt(raw || '', 10);
      if (Number.isFinite(parsed) && parsed >= 260 && parsed <= 900) return parsed;
    } catch {
      return fallback;
    }
    return fallback;
  });
  const [graphs, setGraphs] = useState([]);
  const [agents, setAgents] = useState([]);
  const [kbDocs, setKbDocs] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState('');

  const initialOptions = useMemo(() => initialGraphOptions || [], [initialGraphOptions]);
  const [graphId, setGraphId] = useState(initialOptions[0]?.graph_id || '');

  const [subgraphQuery, setSubgraphQuery] = useState('');
  const [createName, setCreateName] = useState('');
  const [createAgentId, setCreateAgentId] = useState('');

  const [extractMode, setExtractMode] = useState('doc'); // doc | text | category
  const [extractDocId, setExtractDocId] = useState('');
  const [extractText, setExtractText] = useState('');
  const [extractCategories, setExtractCategories] = useState([]);
  const [extractInfo, setExtractInfo] = useState('');
  const [extractProgress, setExtractProgress] = useState(null);

  const [interpretMode, setInterpretMode] = useState('both'); // nodes | communities | both
  const [interpretProgress, setInterpretProgress] = useState(null);
  const [communitySummaries, setCommunitySummaries] = useState([]);
  const [graphStats, setGraphStats] = useState(null);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId || !graphData?.nodes) return null;
    return (graphData.nodes || []).find((n) => n?.id === selectedNodeId) || null;
  }, [graphData, selectedNodeId]);

  const selectedNodeNeighbors = useMemo(() => {
    if (!selectedNodeId || !graphData?.edges || !graphData?.nodes) return [];
    const idToLabel = new Map((graphData.nodes || []).map((n) => [n?.id, n?.label || n?.id]));
    const edges = (graphData.edges || []).filter((e) => e?.from === selectedNodeId || e?.to === selectedNodeId);
    return edges.slice(0, 40).map((e) => {
      const from = e?.from;
      const to = e?.to;
      return {
        id: e?.id || `${from}->${to}:${e?.label || ''}`,
        from,
        to,
        label: e?.label || '',
        fact: e?.fact || '',
        fromLabel: idToLabel.get(from) || from,
        toLabel: idToLabel.get(to) || to,
      };
    });
  }, [graphData, selectedNodeId]);

  useEffect(() => {
    try {
      localStorage.setItem('kg:leftPanelWidth', String(leftPanelWidth));
    } catch {
      return;
    }
  }, [leftPanelWidth]);

  useEffect(() => {
    function clampWidth(w) {
      const min = 280;
      const max = Math.max(min, Math.min(820, window.innerWidth - 360));
      return Math.max(min, Math.min(max, w));
    }

    function onMove(e) {
      if (!resizingRef.current) return;
      const delta = e.clientX - resizeStartRef.current.clientX;
      setLeftPanelWidth(clampWidth(resizeStartRef.current.width + delta));
    }

    function onUp() {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  const enabledAgents = useMemo(() => agents.filter((a) => a.enabled), [agents]);
  const availableCategories = useMemo(() => {
    const set = new Set();
    for (const d of kbDocs || []) {
      for (const c of d?.categories || []) {
        if (typeof c === 'string' && c.trim()) set.add(c.trim());
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [kbDocs]);

  const graphChoices = useMemo(() => {
    const map = new Map();
    for (const o of initialOptions) {
      if (!o?.graph_id) continue;
      map.set(o.graph_id, {
        graph_id: o.graph_id,
        label: `${o.agent_name || '专家'} · ${o.graph_id}`,
      });
    }
    for (const g of graphs || []) {
      if (!g?.graph_id) continue;
      if (map.has(g.graph_id)) continue;
      const name = g.name || '图谱';
      map.set(g.graph_id, { graph_id: g.graph_id, label: `${name} · ${g.graph_id}` });
    }
    return Array.from(map.values());
  }, [initialOptions, graphs]);

  async function reload() {
    setError('');
    const [g, a, d] = await Promise.all([api.listKGGraphs(), api.listAgents(), api.listKBDocuments()]);
    setGraphs(g?.graphs || []);
    setAgents(a || []);
    setKbDocs(d?.documents || []);
    const first = initialOptions[0]?.graph_id || g?.graphs?.[0]?.graph_id || '';
    if (first) setGraphId(first);
  }

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    Promise.resolve()
      .then(() => reload())
      .catch((e) => {
        if (!cancelled) setError(e?.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const renderGraphData = useCallback(async (g) => {
    const [{ Network }, { DataSet }] = await Promise.all([
      import('vis-network/standalone/esm/vis-network.js'),
      import('vis-data/peer/esm/vis-data.js'),
    ]);

    setGraphData(g || null);

    const nodes = new DataSet(
      (g.nodes || []).map((n) => ({
        id: n.id,
        label: n.label,
        group: n.type,
        title: n.summary || n.type || '',
      }))
    );
    const edges = new DataSet(
      (g.edges || []).map((e) => ({
        id: e.id,
        from: e.from,
        to: e.to,
        label: e.label,
        title: e.fact || e.label || '',
        arrows: 'to',
        font: { align: 'middle' },
      }))
    );
    setGraphStats({
      graph_id: g?.graph_id || '',
      nodes: (g?.nodes || []).length,
      edges: (g?.edges || []).length,
    });

    if (!containerRef.current) return;
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }

    networkRef.current = new Network(
      containerRef.current,
      { nodes, edges },
      {
        physics: { stabilization: true },
        nodes: {
          shape: 'dot',
          size: 14,
          font: { size: 14 },
          borderWidth: 1,
        },
        edges: {
          smooth: { type: 'dynamic' },
          color: { color: '#94a3b8' },
        },
        interaction: { hover: true },
      }
    );

    networkRef.current.on('click', (params) => {
      const nid = Array.isArray(params?.nodes) && params.nodes.length > 0 ? params.nodes[0] : '';
      setSelectedNodeId(nid || '');
    });

    networkRef.current.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
  }, []);

  useEffect(() => {
    if (!graphId) return;
    let cancelled = false;
    setIsLoading(true);
    Promise.resolve()
      .then(() => api.getKGGraph(graphId))
      .then(async (g) => {
        if (cancelled || !g) return;
        setError('');
        setSelectedNodeId('');
        setCommunitySummaries(g?.community_summaries?.summaries || []);
        await renderGraphData(g);
      })
      .catch((e) => {
        setGraphStats(null);
        setGraphData(null);
        setSelectedNodeId('');
        if (!cancelled) setError(e?.message || '加载图谱失败');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [graphId, renderGraphData]);

  useEffect(() => {
    function onResize() {
      try {
        networkRef.current?.redraw?.();
        networkRef.current?.fit?.({ animation: false });
      } catch {
        return;
      }
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    try {
      resizeObserverRef.current = new ResizeObserver(() => {
        try {
          networkRef.current?.redraw?.();
        } catch {
          return;
        }
      });
      resizeObserverRef.current.observe(containerRef.current);
    } catch {
      return;
    }
    return () => {
      const observer = resizeObserverRef.current;
      resizeObserverRef.current = null;
      try {
        observer?.disconnect?.();
      } catch {
        return;
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, []);

  async function handleCreateGraph() {
    setExtractInfo('');
    setError('');
    const name = (createName || '').trim();
    if (!name) {
      setError('请先填写图谱名称');
      return;
    }
    setIsLoading(true);
    try {
      const res = await api.createKGGraph({ name, agent_id: (createAgentId || '').trim() });
      const list = await api.listKGGraphs();
      setGraphs(list?.graphs || []);
      if (res?.graph_id) {
        setGraphId(res.graph_id);
        setCreateName('');
      }
    } catch (e) {
      setError(e?.message || '创建图谱失败');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleQuerySubgraph() {
    setExtractInfo('');
    setError('');
    if (!graphId) return;
    const q = (subgraphQuery || '').trim();
    if (!q) {
      setError('请输入要搜索的实体关键词');
      return;
    }
    setIsLoading(true);
    try {
      const g = await api.queryKGSubgraph(graphId, q);
      await renderGraphData(g);
    } catch (e) {
      setError(e?.message || '子图搜索失败');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleExtract() {
    setExtractInfo('');
    setError('');
    if (!graphId) {
      setError('请先选择图谱');
      return;
    }
    cancelExtractRef.current = false;
    setIsLoading(true);
    try {
      if (extractMode === 'doc') {
        const docId = (extractDocId || '').trim();
        if (!docId) {
          setError('请选择知识库文档');
          setIsLoading(false);
          return;
        }
        const d = await api.getKBDocument(docId);
        const text = d?.document?.text || '';
        if (!text.trim()) {
          setError('该文档没有可抽取的内容');
          setIsLoading(false);
          return;
        }
        setExtractProgress({ mode: 'doc', total: 1, done: 0, entities: 0, relations: 0, current: d?.document?.title || docId });
        const r = await api.extractKG({ graph_id: graphId, text });
        const entities = r?.entities ?? 0;
        const relations = r?.relations ?? 0;
        setExtractProgress({ mode: 'doc', total: 1, done: 1, entities, relations, current: d?.document?.title || docId });
        setExtractInfo(`抽取完成：实体 ${entities}，关系 ${relations}`);
      } else if (extractMode === 'text') {
        const text = extractText || '';
        if (!text.trim()) {
          setError('请粘贴要抽取的文本');
          setIsLoading(false);
          return;
        }
        setExtractProgress({ mode: 'text', total: 1, done: 0, entities: 0, relations: 0, current: '粘贴文本' });
        const r = await api.extractKG({ graph_id: graphId, text });
        const entities = r?.entities ?? 0;
        const relations = r?.relations ?? 0;
        setExtractProgress({ mode: 'text', total: 1, done: 1, entities, relations, current: '粘贴文本' });
        setExtractInfo(`抽取完成：实体 ${entities}，关系 ${relations}`);
      } else {
        const cats = Array.isArray(extractCategories) ? extractCategories.filter(Boolean) : [];
        if (cats.length === 0) {
          setError('请选择至少一个分类');
          setIsLoading(false);
          return;
        }
        const docIds = (kbDocs || [])
          .filter((d) => Array.isArray(d.categories) && d.categories.some((c) => cats.includes(c)))
          .map((d) => d.id);
        if (docIds.length === 0) {
          setError('该分类下暂无知识库文档');
          setIsLoading(false);
          return;
        }

        let totalEntities = 0;
        let totalRelations = 0;
        let done = 0;
        setExtractProgress({
          mode: 'category',
          total: docIds.length,
          done: 0,
          entities: 0,
          relations: 0,
          current: `分类：${cats.join('，')}`,
        });

        for (const docId of docIds) {
          if (cancelExtractRef.current) break;
          const meta = (kbDocs || []).find((d) => d.id === docId);
          setExtractProgress((p) => ({
            ...(p || {}),
            current: meta?.title ? `文档：${meta.title}` : `文档：${docId}`,
          }));
          const d = await api.getKBDocument(docId);
          const text = d?.document?.text || '';
          if (!text.trim()) {
            done += 1;
            setExtractProgress({ mode: 'category', total: docIds.length, done, entities: totalEntities, relations: totalRelations, current: meta?.title || docId });
            continue;
          }
          const r = await api.extractKG({ graph_id: graphId, text });
          totalEntities += r?.entities ?? 0;
          totalRelations += r?.relations ?? 0;
          done += 1;
          setExtractProgress({
            mode: 'category',
            total: docIds.length,
            done,
            entities: totalEntities,
            relations: totalRelations,
            current: meta?.title || docId,
          });
        }

        if (cancelExtractRef.current) {
          setExtractInfo(`已停止：已处理 ${done}/${docIds.length} 篇文档，累计实体 ${totalEntities}，关系 ${totalRelations}`);
        } else {
          setExtractInfo(`抽取完成：共 ${docIds.length} 篇文档，累计实体 ${totalEntities}，关系 ${totalRelations}`);
        }
      }

      const g = await api.getKGGraph(graphId);
      setCommunitySummaries(g?.community_summaries?.summaries || []);
      await renderGraphData(g);
    } catch (e) {
      setError(e?.message || '抽取失败（请检查 Neo4j 配置/模型可用性）');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleInterpret() {
    setError('');
    setInterpretProgress(null);
    setCommunitySummaries([]);
    if (!graphId) {
      setError('请先选择图谱');
      return;
    }
    setIsLoading(true);
    try {
      await api.interpretKGStream(graphId, { mode: interpretMode }, (type, evt) => {
        if (type === 'nodes_start') {
          setInterpretProgress({ phase: 'nodes', total: evt.total || 0, current: 0, interpreted: 0, entity: '' });
        } else if (type === 'node_progress') {
          setInterpretProgress((p) => ({ ...(p || {}), phase: 'nodes', total: evt.total || p?.total || 0, current: evt.current || p?.current || 0, entity: evt.entity || '' }));
        } else if (type === 'node_done') {
          setInterpretProgress((p) => ({ ...(p || {}), phase: 'nodes', total: evt.total || p?.total || 0, current: evt.current || p?.current || 0, interpreted: evt.interpreted ?? p?.interpreted ?? 0 }));
        } else if (type === 'communities_start') {
          setInterpretProgress({ phase: 'communities', total: evt.total || 0, current: 0, interpreted: 0, entity: '' });
        } else if (type === 'community_progress') {
          setInterpretProgress((p) => ({ ...(p || {}), phase: 'communities', total: evt.total || p?.total || 0, current: evt.current || p?.current || 0 }));
        } else if (type === 'communities_complete') {
          setCommunitySummaries(evt.communities || []);
        } else if (type === 'error') {
          setError(evt.message || '生成解读失败');
        } else if (type === 'complete') {
          if (Array.isArray(evt.communities)) setCommunitySummaries(evt.communities);
        }
      });
      const g = await api.getKGGraph(graphId);
      setCommunitySummaries(g?.community_summaries?.summaries || []);
      await renderGraphData(g);
    } catch (e) {
      setError(e?.message || '生成解读失败');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="gpage">
      <div className="gpage-toolbar">
        <div className="gpage-toolbar-left">
          <div className="gpage-title">知识图谱</div>
          <div className="gpage-subtitle">
            抽取、检索、可视化，并生成节点解读与主题摘要
            {graphStats?.graph_id ? ` · ${graphStats.graph_id}` : ''}
            {typeof graphStats?.nodes === 'number' ? ` · 节点 ${graphStats.nodes}` : ''}
            {typeof graphStats?.edges === 'number' ? ` · 关系 ${graphStats.edges}` : ''}
          </div>
        </div>
        <div className="gpage-toolbar-right">
          <button className="gpage-btn" onClick={() => setIsPanelCollapsed((v) => !v)} disabled={isLoading}>
            {isPanelCollapsed ? '展开面板' : '收起面板'}
          </button>
          <button className="gpage-btn" onClick={() => reload()} disabled={isLoading}>
            刷新
          </button>
          <button className="gpage-btn secondary" onClick={onBack}>
            返回聊天
          </button>
        </div>
      </div>

      <div className="gpage-body">
        <div
          className={`gpage-grid ${isPanelCollapsed ? 'collapsed' : ''}`}
          style={
            isPanelCollapsed
              ? undefined
              : {
                  '--left-panel-width': `${leftPanelWidth}px`,
                }
          }
        >
          <div className="gpage-left" style={isPanelCollapsed ? { display: 'none' } : undefined}>
            {error && <div className="gpage-error">{error}</div>}
            {extractInfo && <div className="gpage-hint">{extractInfo}</div>}

            <div className="gcard">
              <div className="gcard-title">选择图谱</div>
              <select value={graphId} onChange={(e) => setGraphId(e.target.value)} className="ginput">
                {graphChoices.length === 0 ? <option value="">（暂无图谱）</option> : null}
                {graphChoices.map((o) => (
                  <option key={o.graph_id} value={o.graph_id}>
                    {o.label}
                  </option>
                ))}
              </select>
              <div className="gcard-row">
                <input
                  className="ginput"
                  value={subgraphQuery}
                  onChange={(e) => setSubgraphQuery(e.target.value)}
                  placeholder="子图搜索：输入实体关键词"
                />
                <button className="gpage-btn" onClick={handleQuerySubgraph} disabled={isLoading || !graphId}>
                  搜索
                </button>
              </div>
              <div className="gcard-row">
                <button
                  className="gpage-btn secondary"
                  onClick={async () => {
                    if (!graphId) return;
                    setIsLoading(true);
                    setError('');
                    try {
                      const g = await api.getKGGraph(graphId);
                      setCommunitySummaries(g?.community_summaries?.summaries || []);
                      await renderGraphData(g);
                    } catch (e) {
                      setError(e?.message || '加载图谱失败');
                    } finally {
                      setIsLoading(false);
                    }
                  }}
                  disabled={isLoading || !graphId}
                >
                  重置全图
                </button>
              </div>
            </div>

            <div className="gcard">
              <div className="gcard-title">创建图谱</div>
              <input
                className="ginput"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="例如：数据专家知识图谱"
              />
              <select className="ginput" value={createAgentId} onChange={(e) => setCreateAgentId(e.target.value)}>
                <option value="">（不绑定专家）</option>
                {enabledAgents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <button className="gpage-btn primary" onClick={handleCreateGraph} disabled={isLoading}>
                创建
              </button>
              <div className="gpage-hint">绑定专家后：若该专家未配置 graph_id，会自动绑定到新图谱。</div>
            </div>

            <div className="gcard">
              <div className="gcard-title">抽取写入</div>
              <select className="ginput" value={extractMode} onChange={(e) => setExtractMode(e.target.value)}>
                <option value="doc">从知识库文档抽取</option>
                <option value="category">按分类批量抽取</option>
                <option value="text">从粘贴文本抽取</option>
              </select>
              {extractMode === 'doc' ? (
                <select className="ginput" value={extractDocId} onChange={(e) => setExtractDocId(e.target.value)}>
                  <option value="">（选择文档）</option>
                  {kbDocs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title} · {d.id}
                    </option>
                  ))}
                </select>
              ) : extractMode === 'category' ? (
                <MultiSelectDropdown
                  label="分类"
                  options={availableCategories}
                  value={extractCategories}
                  onChange={setExtractCategories}
                  placeholder="选择分类..."
                  createPlaceholder="新建分类（回车添加）"
                />
              ) : (
                <textarea
                  className="gtextarea"
                  value={extractText}
                  onChange={(e) => setExtractText(e.target.value)}
                  rows={5}
                  placeholder="粘贴一段文本，用于抽取实体与关系并写入 Neo4j"
                />
              )}
              <button className="gpage-btn primary" onClick={handleExtract} disabled={isLoading || !graphId}>
                抽取并写入
              </button>
              {extractProgress && (
                <div className="gprogress">
                  <div className="gprogress-top">
                    <div className="gprogress-text">{extractProgress.current || '抽取中...'}</div>
                    <div className="gprogress-metrics">
                      {typeof extractProgress.done === 'number' && typeof extractProgress.total === 'number'
                        ? `${extractProgress.done}/${extractProgress.total}`
                        : ''}
                      {typeof extractProgress.entities === 'number' ? ` · 实体 ${extractProgress.entities}` : ''}
                      {typeof extractProgress.relations === 'number' ? ` · 关系 ${extractProgress.relations}` : ''}
                    </div>
                  </div>
                  <div className="gprogress-bar">
                    <div
                      className="gprogress-bar-fill"
                      style={{
                        width:
                          extractProgress.total > 0
                            ? `${Math.round((extractProgress.done / extractProgress.total) * 100)}%`
                            : '0%',
                      }}
                    />
                  </div>
                  <div className="gprogress-actions">
                    <button className="gpage-btn secondary" onClick={() => (cancelExtractRef.current = true)} disabled={!isLoading}>
                      停止
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="gcard">
              <div className="gcard-title">节点解读 / 主题摘要</div>
              <select className="ginput" value={interpretMode} onChange={(e) => setInterpretMode(e.target.value)}>
                <option value="both">节点解读 + 社区摘要</option>
                <option value="nodes">仅节点解读</option>
                <option value="communities">仅社区摘要</option>
              </select>
              <button className="gpage-btn primary" onClick={handleInterpret} disabled={isLoading || !graphId}>
                生成解读
              </button>
              {interpretProgress && (
                <div className="gprogress">
                  <div className="gprogress-top">
                    <div className="gprogress-text">
                      {interpretProgress.phase === 'nodes'
                        ? `节点解读：${interpretProgress.entity || ''}`
                        : '社区摘要生成中...'}
                    </div>
                    <div className="gprogress-metrics">
                      {interpretProgress.total > 0
                        ? `${interpretProgress.current}/${interpretProgress.total}`
                        : ''}
                      {interpretProgress.phase === 'nodes' && typeof interpretProgress.interpreted === 'number'
                        ? ` · 已写回 ${interpretProgress.interpreted}`
                        : ''}
                    </div>
                  </div>
                  <div className="gprogress-bar">
                    <div
                      className="gprogress-bar-fill"
                      style={{
                        width:
                          interpretProgress.total > 0
                            ? `${Math.round((interpretProgress.current / interpretProgress.total) * 100)}%`
                            : '0%',
                      }}
                    />
                  </div>
                </div>
              )}
            </div>

            {communitySummaries.length > 0 && (
              <div className="gcard">
                <div className="gcard-title">社区摘要（{communitySummaries.length}）</div>
                <div className="gcommunity">
                  {communitySummaries.map((c) => (
                    <div key={c.community_index} className="gcommunity-card">
                      <div className="gcommunity-title">
                        {c.title || `社区 ${c.community_index}`} {c.size ? `（${c.size} 节点）` : ''}
                      </div>
                      <div className="gcommunity-summary">{c.summary}</div>
                      {Array.isArray(c.key_entities) && c.key_entities.length > 0 && (
                        <div className="gcommunity-meta">关键实体：{c.key_entities.slice(0, 12).join('，')}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {!isPanelCollapsed ? (
            <div
              className="gpage-resizer"
              onMouseDown={(e) => {
                resizingRef.current = true;
                resizeStartRef.current = { clientX: e.clientX, width: leftPanelWidth };
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
              }}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize panel"
              title="拖拽调整左侧面板宽度"
            />
          ) : null}

          <div className={`gpage-right ${selectedNode ? 'has-details' : ''}`}>
            <div className="gcanvas-wrap">
              <div className="gcanvas" ref={containerRef} />
              {!graphId ? <div className="gcanvas-empty">请选择或创建图谱</div> : null}
              {graphId && graphStats && graphStats.nodes === 0 ? (
                <div className="gcanvas-empty">该图谱暂无节点，请先抽取写入</div>
              ) : null}
              {isLoading ? <div className="gcanvas-loading">处理中...</div> : null}
            </div>

            {selectedNode ? (
              <div className="gdetails">
                <div className="gdetails-head">
                  <div className="gdetails-title">{selectedNode.label || selectedNode.id}</div>
                  <button className="gpage-btn secondary" onClick={() => setSelectedNodeId('')} disabled={isLoading}>
                    关闭
                  </button>
                </div>
                <div className="gdetails-meta">
                  {selectedNode.type ? <span className="gdetails-pill">{selectedNode.type}</span> : null}
                  {selectedNode.id ? <span className="gdetails-id">{selectedNode.id}</span> : null}
                </div>

                {selectedNode.summary ? <div className="gdetails-section">{selectedNode.summary}</div> : null}

                {Array.isArray(selectedNode?.attributes?.key_facts) && selectedNode.attributes.key_facts.length > 0 ? (
                  <div className="gdetails-section">
                    <div className="gdetails-section-title">关键事实</div>
                    <ul className="gdetails-list">
                      {selectedNode.attributes.key_facts.slice(0, 20).map((f, i) => (
                        <li key={`${i}:${f}`}>{String(f)}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {selectedNodeNeighbors.length > 0 ? (
                  <div className="gdetails-section">
                    <div className="gdetails-section-title">相邻关系（{selectedNodeNeighbors.length}）</div>
                    <div className="gdetails-rel-list">
                      {selectedNodeNeighbors.map((r) => (
                        <div key={r.id} className="gdetails-rel">
                          <div className="gdetails-rel-top">
                            <span className="gdetails-rel-node">{r.fromLabel}</span>
                            <span className="gdetails-rel-edge">{r.label || '关系'}</span>
                            <span className="gdetails-rel-node">{r.toLabel}</span>
                          </div>
                          {r.fact ? <div className="gdetails-rel-fact">{r.fact}</div> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {selectedNode.attributes && Object.keys(selectedNode.attributes).length > 0 ? (
                  <div className="gdetails-section">
                    <div className="gdetails-section-title">属性</div>
                    <pre className="gdetails-pre">{JSON.stringify(selectedNode.attributes, null, 2)}</pre>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
