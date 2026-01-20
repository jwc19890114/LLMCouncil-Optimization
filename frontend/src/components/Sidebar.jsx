import { useEffect, useMemo, useState } from 'react';
import './Sidebar.css';

function loadBool(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === '1';
  } catch {
    return fallback;
  }
}

function saveBool(key, value) {
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // ignore
  }
}

function loadStr(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return String(raw);
  } catch {
    return fallback;
  }
}

function saveStr(key, value) {
  try {
    localStorage.setItem(key, String(value ?? ''));
  } catch {
    // ignore
  }
}

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore
  }
}

function useCollapsible(key, defaultCollapsed) {
  const [collapsed, setCollapsed] = useState(() => loadBool(key, defaultCollapsed));
  useEffect(() => {
    saveBool(key, collapsed);
  }, [key, collapsed]);
  return [collapsed, setCollapsed];
}

function useStoredString(key, defaultValue) {
  const [value, setValue] = useState(() => loadStr(key, defaultValue));
  useEffect(() => {
    saveStr(key, value);
  }, [key, value]);
  return [value, setValue];
}

function Section({ title, subtitle, collapsed, onToggle, grow, children, actions }) {
  return (
    <div className={`sidebar-section ${grow ? 'grow' : ''}`}>
      <div className="sidebar-section-header">
        <button className="sidebar-section-toggle" onClick={onToggle} type="button">
          <span className={`sidebar-chevron ${collapsed ? 'collapsed' : ''}`}>▾</span>
          <span className="sidebar-section-title">{title}</span>
        </button>
        {actions ? <div className="sidebar-section-actions">{actions}</div> : null}
      </div>
      {subtitle ? <div className="sidebar-section-subtitle">{subtitle}</div> : null}
      {!collapsed ? <div className="sidebar-section-body">{children}</div> : null}
    </div>
  );
}

export default function Sidebar({
  conversations,
  projects,
  status,
  currentConversationId,
  currentConversation,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onExportConversation,
  onCreateProject,
  onSetConversationArchived,
  onSetConversationProject,
  activeView,
  onManageAgents,
  onManageKnowledgeBase,
  onManagePlugins,
  onManageSettings,
  onShowChat,
  onShowGraph,
}) {
  const allAgents = status?.agents || [];
  const enabledAgents = allAgents.filter((a) => a.enabled);

  const selectedIds = currentConversation?.agent_ids;
  const selectedAgents = useMemo(() => {
    return Array.isArray(selectedIds) && selectedIds.length > 0
      ? enabledAgents.filter((a) => selectedIds.includes(a.id))
      : enabledAgents;
  }, [enabledAgents, selectedIds]);

  const chairmanSpec = status?.chairman_model?.spec || '';
  const chairmanAgent = allAgents.find((a) => a.model_spec === chairmanSpec);

  const isSmallScreen = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
  }, []);

  const [expertsCollapsed, setExpertsCollapsed] = useCollapsible('sidebar:expertsCollapsed', isSmallScreen);
  const [toolsCollapsed, setToolsCollapsed] = useCollapsible('sidebar:toolsCollapsed', isSmallScreen);
  const [convsCollapsed, setConvsCollapsed] = useCollapsible('sidebar:convsCollapsed', false);
  const [showArchived, setShowArchived] = useCollapsible('sidebar:showArchived', false);
  const [projectFilter, setProjectFilter] = useStoredString('sidebar:projectFilter', 'all'); // all | none | project_id
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectDraft, setProjectDraft] = useState('');
  const [moveConvId, setMoveConvId] = useState('');
  const [collapsedProjectGroups, setCollapsedProjectGroups] = useState(() => {
    const arr = loadJson('sidebar:collapsedProjectGroups', []);
    return new Set(Array.isArray(arr) ? arr.map((x) => String(x)) : []);
  });

  useEffect(() => {
    saveJson('sidebar:collapsedProjectGroups', Array.from(collapsedProjectGroups));
  }, [collapsedProjectGroups]);

  const isGroupCollapsed = (groupKey) => collapsedProjectGroups.has(String(groupKey));
  const toggleGroupCollapsed = (groupKey) => {
    const key = String(groupKey);
    setCollapsedProjectGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const expertsTitle = useMemo(() => {
    const total = enabledAgents.length;
    const picked = Array.isArray(selectedIds) && selectedIds.length > 0 ? selectedAgents.length : null;
    const chairmanLabel = chairmanAgent?.name || chairmanSpec || '';
    if (picked !== null) {
      return `专家库（${picked}/${total}）${chairmanLabel ? ` · Chairman：${chairmanLabel}` : ''}`;
    }
    return `专家库（${total}）${chairmanLabel ? ` · Chairman：${chairmanLabel}` : ''}`;
  }, [enabledAgents.length, selectedAgents.length, selectedIds, chairmanAgent?.name, chairmanSpec]);

  const toolsTitle = '功能栏';
  const convsTitle = `会话组（${conversations.length}）`;

  const projectsList = Array.isArray(projects) ? projects : [];

  const { visibleConversations, archivedConversations } = useMemo(() => {
    const all = Array.isArray(conversations) ? conversations : [];
    const active = all.filter((c) => !c?.archived);
    const archived = all.filter((c) => !!c?.archived);
    const normalize = (c) => ({
      ...c,
      archived: !!c?.archived,
      project_id: String(c?.project_id || ''),
    });
    return { visibleConversations: active.map(normalize), archivedConversations: archived.map(normalize) };
  }, [conversations]);

  const groupedConversations = useMemo(() => {
    const byProject = new Map();
    for (const p of projectsList) {
      if (!p?.id) continue;
      byProject.set(String(p.id), { id: String(p.id), name: String(p.name || 'Project'), conversations: [] });
    }
    const noProject = { id: '', name: 'No Project', conversations: [] };

    const pool =
      projectFilter === 'all'
        ? visibleConversations
        : projectFilter === 'none'
          ? visibleConversations.filter((c) => !c.project_id)
          : visibleConversations.filter((c) => c.project_id === projectFilter);

    for (const c of pool) {
      const pid = String(c.project_id || '');
      if (!pid) {
        noProject.conversations.push(c);
        continue;
      }
      const g = byProject.get(pid);
      if (g) g.conversations.push(c);
      else noProject.conversations.push({ ...c, project_id: '' });
    }

    const groups = [];
    if (projectFilter === 'all') {
      for (const g of Array.from(byProject.values()).sort((a, b) => a.name.localeCompare(b.name))) {
        if (g.conversations.length) groups.push(g);
      }
      if (noProject.conversations.length) groups.push(noProject);
      return groups;
    }

    if (projectFilter === 'none') {
      return noProject.conversations.length ? [noProject] : [];
    }

    const g = byProject.get(projectFilter);
    return g && g.conversations.length ? [g] : [];
  }, [projectsList, visibleConversations, projectFilter]);

  return (
    <div className="sidebar">
      <div className="sidebar-top">
        <div className="sidebar-brand">SynthesisLab</div>
      </div>

      <Section
        title={expertsTitle}
        collapsed={expertsCollapsed}
        onToggle={() => setExpertsCollapsed((v) => !v)}
        subtitle={enabledAgents.length > 0 ? '点击会话内“选择专家”可更改本会话成员' : '尚未配置专家'}
      >
        <div className="agents-list">
          {selectedAgents.map((a) => (
            <div key={a.id} className="agent-item" title={a.model_spec}>
              <div className="agent-name">{a.name}</div>
              <div className="agent-model">{a.model_spec}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section title={toolsTitle} collapsed={toolsCollapsed} onToggle={() => setToolsCollapsed((v) => !v)}>
        <div className="agents-actions">
          {activeView !== 'chat' ? (
            <button className="agents-btn" onClick={onShowChat} type="button">
              返回聊天
            </button>
          ) : null}
          <button className="agents-btn" onClick={onManageAgents} type="button">
            管理 Agents
          </button>
          <button className="agents-btn" onClick={onManageKnowledgeBase} type="button">
            知识库
          </button>
          <button className="agents-btn" onClick={onManagePlugins} type="button">
            插件
          </button>
          <button className="agents-btn" onClick={onShowGraph} type="button">
            图谱
          </button>
          <button className="agents-btn" onClick={onManageSettings} type="button">
            流程设置
          </button>
        </div>
      </Section>

      <Section
        title={convsTitle}
        collapsed={convsCollapsed}
        onToggle={() => setConvsCollapsed((v) => !v)}
        grow
        actions={
          <button className="new-conversation-btn small" onClick={onNewConversation} type="button">
            + 新建
          </button>
        }
      >
        <div className="sidebar-conv-controls">
          <select className="sidebar-select" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="all">全部项目</option>
            <option value="none">未归类</option>
            {projectsList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name || p.id}
              </option>
            ))}
          </select>
          <button
            className="icon-btn"
            type="button"
            title="新建项目"
            onClick={() => {
              setCreatingProject((v) => !v);
              setProjectDraft('');
            }}
          >
            + 项目
          </button>
          <button className="icon-btn" type="button" title="归档" onClick={() => setShowArchived((v) => !v)}>
            {showArchived ? '隐藏归档' : '归档'}
          </button>
        </div>

        {creatingProject ? (
          <div className="sidebar-project-create">
            <input
              className="sidebar-input"
              value={projectDraft}
              onChange={(e) => setProjectDraft(e.target.value)}
              placeholder="项目名称"
            />
            <button
              className="icon-btn"
              type="button"
              onClick={() => {
                const name = String(projectDraft || '').trim();
                if (!name) return;
                onCreateProject?.(name);
                setCreatingProject(false);
                setProjectDraft('');
              }}
            >
              创建
            </button>
            <button
              className="icon-btn"
              type="button"
              onClick={() => {
                setCreatingProject(false);
                setProjectDraft('');
              }}
            >
              取消
            </button>
          </div>
        ) : null}

        <div className="conversation-list">
          {visibleConversations.length === 0 ? (
            <div className="no-conversations">暂无会话</div>
          ) : (
            <>
              {groupedConversations.map((group) => (
                <div
                  key={`group:${group.id || 'none'}`}
                  className={`project-group ${isGroupCollapsed(`group:${group.id || 'none'}`) ? 'collapsed' : ''}`}
                >
                  <button
                    className="project-group-header project-group-toggle"
                    type="button"
                    onClick={() => toggleGroupCollapsed(`group:${group.id || 'none'}`)}
                    title="折叠/展开"
                  >
                    <span
                      className={`project-chevron ${isGroupCollapsed(`group:${group.id || 'none'}`) ? 'collapsed' : ''}`}
                    >
                      ▾
                    </span>
                    <span className="project-group-name">{group.name}</span>
                    <span className="project-badge">{group.conversations.length}</span>
                  </button>
                  {isGroupCollapsed(`group:${group.id || 'none'}`)
                    ? null
                    : group.conversations.map((conv) => (
                    <div
                      key={conv.id}
                      className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''}`}
                      onClick={() => onSelectConversation(conv.id)}
                    >
                      <div className="conversation-row">
                        <div className="conversation-main">
                          <div className="conversation-title">{conv.title || 'New Conversation'}</div>
                          <div className="conversation-meta">{conv.message_count} 条消息</div>
                        </div>
                        <div className="conversation-actions">
                          <button
                            className="icon-btn"
                            title="移动"
                            onClick={(e) => {
                              e.stopPropagation();
                              setMoveConvId((prev) => (prev === conv.id ? '' : conv.id));
                            }}
                            type="button"
                          >
                            移动
                          </button>
                          <button
                            className="icon-btn"
                            title="归档"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSetConversationArchived?.(conv.id, true);
                            }}
                            type="button"
                          >
                            归档
                          </button>
                          <button
                            className="icon-btn"
                            title="导出"
                            onClick={(e) => {
                              e.stopPropagation();
                              onExportConversation?.(conv.id);
                            }}
                            type="button"
                          >
                            导出
                          </button>
                          <button
                            className="icon-btn danger"
                            title="删除"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteConversation?.(conv.id);
                            }}
                            type="button"
                          >
                            删除
                          </button>
                        </div>
                      </div>

                      {moveConvId === conv.id ? (
                        <div className="conversation-move">
                          <select
                            className="sidebar-select"
                            value={conv.project_id || ''}
                            onChange={(e) => {
                              const v = e.target.value;
                              onSetConversationProject?.(conv.id, v);
                              setMoveConvId('');
                            }}
                          >
                            <option value="">未归类</option>
                            {projectsList.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name || p.id}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ))}

              {showArchived ? (
                <div className="project-group">
                  <button
                    className="project-group-header project-group-toggle"
                    type="button"
                    onClick={() => toggleGroupCollapsed('group:archived')}
                    title="折叠/展开"
                  >
                    <span className={`project-chevron ${isGroupCollapsed('group:archived') ? 'collapsed' : ''}`}>
                      ▾
                    </span>
                    <span className="project-group-name">归档</span>
                    <span className="project-badge">{archivedConversations.length}</span>
                  </button>
                  {isGroupCollapsed('group:archived')
                    ? null
                    : archivedConversations.map((conv) => (
                    <div
                      key={conv.id}
                      className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''}`}
                      onClick={() => onSelectConversation(conv.id)}
                    >
                      <div className="conversation-row">
                        <div className="conversation-main">
                          <div className="conversation-title">{conv.title || 'New Conversation'}</div>
                          <div className="conversation-meta">{conv.message_count} 条消息</div>
                        </div>
                        <div className="conversation-actions">
                          <button
                            className="icon-btn"
                            title="恢复"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSetConversationArchived?.(conv.id, false);
                            }}
                            type="button"
                          >
                            恢复
                          </button>
                          <button
                            className="icon-btn danger"
                            title="删除"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteConversation?.(conv.id);
                            }}
                            type="button"
                          >
                            删除
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      </Section>
    </div>
  );
}
