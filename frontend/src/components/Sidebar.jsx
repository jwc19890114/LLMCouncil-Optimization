import './Sidebar.css';

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
  onManageSettings,
  onShowChat,
  onShowGraph,
}) {
  const allAgents = status?.agents || [];
  const enabledAgents = allAgents.filter((a) => a.enabled);

  const selectedIds = currentConversation?.agent_ids;
  const selectedAgents =
    Array.isArray(selectedIds) && selectedIds.length > 0
      ? enabledAgents.filter((a) => selectedIds.includes(a.id))
      : enabledAgents;

  const chairmanSpec = status?.chairman_model?.spec;
  const chairmanAgent = allAgents.find((a) => a.model_spec === chairmanSpec);

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        {enabledAgents.length > 0 && (
          <div className="agents">
            <div className="agents-title">
              专家库：{enabledAgents.length}
              {Array.isArray(selectedIds) && selectedIds.length > 0
                ? `（本会话：${selectedAgents.length}）`
                : ''}
              {chairmanAgent?.name
                ? `（Chairman：${chairmanAgent.name}）`
                : chairmanSpec
                ? `（Chairman：${chairmanSpec}）`
                : ''}
            </div>
            <div className="agents-list">
              {selectedAgents.map((a) => (
                <div key={a.id} className="agent-item" title={a.model_spec}>
                  <div className="agent-name">{a.name}</div>
                  <div className="agent-model">{a.model_spec}</div>
                </div>
              ))}
            </div>
            <div className="agents-actions">
              {activeView === 'kb' ? (
                <button className="agents-btn" onClick={onShowChat}>
                  返回聊天
                </button>
              ) : null}
              <button className="agents-btn" onClick={onManageAgents}>
                管理 Agents
              </button>
              <button className="agents-btn" onClick={onManageKnowledgeBase}>
                知识库
              </button>
              <button className="agents-btn" onClick={onShowGraph}>
                图谱
              </button>
              <button className="agents-btn" onClick={onManageSettings}>
                流程设置
              </button>
            </div>
          </div>
        )}
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + 新建会话
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">暂无会话</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-row">
                <div className="conversation-main">
                  <div className="conversation-title">
                    {conv.title || 'New Conversation'}
                  </div>
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
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
