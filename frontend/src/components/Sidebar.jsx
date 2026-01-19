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

function useCollapsible(key, defaultCollapsed) {
  const [collapsed, setCollapsed] = useState(() => loadBool(key, defaultCollapsed));
  useEffect(() => {
    saveBool(key, collapsed);
  }, [key, collapsed]);
  return [collapsed, setCollapsed];
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
  status,
  currentConversationId,
  currentConversation,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onExportConversation,
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
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <div className="no-conversations">暂无会话</div>
          ) : (
            conversations.map((conv) => (
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
              </div>
            ))
          )}
        </div>
      </Section>
    </div>
  );
}
