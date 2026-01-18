import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import Stage0 from './Stage0';
import Stage2b from './Stage2b';
import Stage2c from './Stage2c';
import Stage4 from './Stage4';
import './ChatInterface.css';

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
  onExportConversation,
  onSelectAgents,
  onShowGraph,
  graphOptions,
  onRefreshConversation,
  chairmanOptions,
  defaultChairmanLabel,
}) {
  const [input, setInput] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isReportReqOpen, setIsReportReqOpen] = useState(false);
  const [reportRequirementsDraft, setReportRequirementsDraft] = useState('');
  const [trace, setTrace] = useState([]);
  const [showTrace, setShowTrace] = useState(false);
  const [traceError, setTraceError] = useState('');
  const [expandedTraceIndex, setExpandedTraceIndex] = useState(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  useEffect(() => {
    if (!conversation?.id) return;
    let cancelled = false;
    api
      .getConversationTrace(conversation.id)
      .then((r) => {
        if (!cancelled) {
          setTrace(r?.events || []);
          setTraceError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setTraceError(e?.message || 'Trace 加载失败');
      });
    return () => {
      cancelled = true;
    };
  }, [conversation?.id]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>欢迎使用 LLM Council</h2>
          <p>请先新建一个会话开始</p>
        </div>
      </div>
    );
  }

  async function handleUploadTextFile(file) {
    if (!conversation?.id || !file) return;
    setUploadError('');
    setIsUploading(true);
    try {
      const sizeLimit = 5 * 1024 * 1024;
      if (file.size > sizeLimit) {
        throw new Error('文件过大（限制 5MB），请先裁剪后再上传');
      }
      const text = await file.text();
      if (!text.trim()) throw new Error('文件内容为空');

      const title = file.name || 'uploaded.txt';
      const source = `upload:${title}`;

      const created = await api.addKBDocument({
        title,
        source,
        text,
        categories: ['upload'],
        agent_ids: [],
      });
      const docId = created?.doc_id;
      if (!docId) throw new Error('上传失败：未返回 doc_id');

      const existing = Array.isArray(conversation?.kb_doc_ids) ? conversation.kb_doc_ids : [];
      const next = Array.from(new Set([...existing, docId]));
      await api.setConversationKBDocIds(conversation.id, next);

      // Optional: refresh conversation in parent if provided.
      if (typeof onRefreshConversation === 'function') {
        await onRefreshConversation();
      }

      const ok = confirm(`已上传并绑定到当前会话：${title}\n\n是否立即让专家委员会对该文档做“摘要/要点/风险/建议”的讨论解读？`);
      if (ok) {
        onSendMessage(
          `请对我上传的文本文件《${title}》进行分析讨论与解读：\n` +
            `1) 用 5~10 句话给出摘要\n` +
            `2) 列出关键要点（条目化）\n` +
            `3) 识别潜在问题/风险/逻辑漏洞（如有）\n` +
            `4) 给出可执行的改进建议与下一步行动`
        );
      }
    } catch (e) {
      setUploadError(e?.message || '上传失败');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div className="chat-interface">
      <div className="chat-toolbar">
        <div className="chat-toolbar-left">
          <div className="chat-title">{conversation.title || 'Conversation'}</div>
        </div>
        <div className="chat-toolbar-right">
          <input
            ref={fileInputRef}
            type="file"
            accept="text/*,.txt,.md,.json,.csv"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUploadTextFile(f);
            }}
          />
          <button
            className="toolbar-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || isUploading}
            title="上传文本文件并绑定到当前会话"
          >
            {isUploading ? '上传中...' : '上传文本'}
          </button>
          {Array.isArray(chairmanOptions) && chairmanOptions.length > 0 ? (
            <select
              className="toolbar-btn"
              value={conversation?.chairman_agent_id || ''}
              disabled={isLoading || isUploading}
              title="为当前会话指定 Chairman（仅影响最终综合阶段）"
              onChange={async (e) => {
                const v = e.target.value || '';
                try {
                  await api.setConversationChairman(conversation.id, { chairman_agent_id: v });
                  await onRefreshConversation?.();
                } catch (err) {
                  setUploadError(err?.message || '设置 Chairman 失败');
                }
              }}
            >
              <option value="">{`跟随默认（${defaultChairmanLabel || '未设置'}）`}</option>
              {chairmanOptions.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          ) : null}
          <button className="toolbar-btn" onClick={onSelectAgents}>
            选择专家
          </button>
          {Array.isArray(graphOptions) && graphOptions.length > 0 && (
            <button className="toolbar-btn" onClick={onShowGraph}>
              图谱
            </button>
          )}
          <button className="toolbar-btn" onClick={() => setShowTrace((v) => !v)}>
            {showTrace ? '隐藏过程' : '显示过程'}
          </button>
          <button
            className="toolbar-btn"
            onClick={() => {
              setReportRequirementsDraft(conversation?.report_requirements || '');
              setIsReportReqOpen(true);
            }}
            disabled={isLoading || isUploading}
            title="设置本会话的报告撰写要求（用于阶段4报告）"
          >
            报告要求
          </button>
          <button className="toolbar-btn" onClick={onExportConversation}>
            导出
          </button>
        </div>
      </div>

      {isReportReqOpen && (
        <div className="chat-modal-overlay" onClick={() => setIsReportReqOpen(false)}>
          <div className="chat-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chat-modal-header">
              <div className="chat-modal-title">报告要求（本会话）</div>
              <button className="chat-modal-close" onClick={() => setIsReportReqOpen(false)}>
                ✕
              </button>
            </div>
            <div className="chat-modal-body">
              <div className="chat-modal-hint">
                留空则使用“流程设置”里的默认报告模板。修改后会在下一次讨论结束后的报告生成中生效。
              </div>
              <textarea
                className="chat-modal-textarea"
                value={reportRequirementsDraft}
                onChange={(e) => setReportRequirementsDraft(e.target.value)}
                rows={10}
                placeholder="例如：请以“专利撰写视角”输出；必须包含：摘要/创新点/风险/实施方案/引用依据..."
              />
            </div>
            <div className="chat-modal-actions">
              <button className="toolbar-btn" onClick={() => setIsReportReqOpen(false)} disabled={isLoading}>
                取消
              </button>
              <button
                className="toolbar-btn primary"
                onClick={async () => {
                  try {
                    await api.setConversationReport(conversation.id, {
                      report_requirements: reportRequirementsDraft,
                    });
                    await onRefreshConversation?.();
                    setIsReportReqOpen(false);
                  } catch (err) {
                    setUploadError(err?.message || '设置报告要求失败');
                  }
                }}
                disabled={isLoading}
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {showTrace && (
        <div className="trace-panel">
          <div className="trace-title">讨论过程（Trace）</div>
          {uploadError ? <div className="trace-error">{uploadError}</div> : null}
          {traceError ? (
            <div className="trace-error">{traceError}</div>
          ) : (
            <div className="trace-list">
              {trace.length === 0 ? (
                <div className="trace-empty">暂无 Trace（发送消息后会记录）</div>
              ) : (
                trace.slice(-200).map((e, idx) => (
                  <div key={idx} className="trace-item">
                    <div
                      className="trace-meta"
                      onClick={() =>
                        setExpandedTraceIndex((p) => (p === idx ? null : idx))
                      }
                      role="button"
                      tabIndex={0}
                    >
                      <span className="trace-ts">{e.ts || ''}</span>
                      <span className="trace-type">{e.type}</span>
                      {e.stage && <span className="trace-stage">{e.stage}</span>}
                      {e.agent?.name && <span className="trace-agent">{e.agent.name}</span>}
                      {typeof e.duration_ms === 'number' && (
                        <span className="trace-dur">{e.duration_ms}ms</span>
                      )}
                      {e.ok === false && <span className="trace-bad">FAIL</span>}
                    </div>
                    {e.error && <div className="trace-errorline">{e.error}</div>}
                    {expandedTraceIndex === idx && e.type === 'llm_call' && (
                      <pre className="trace-detail">
{JSON.stringify(
  {
    stage: e.stage,
    agent: e.agent,
    request: e.request,
    response: e.response,
  },
  null,
  2
)}
                      </pre>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>开始对话</h2>
            <p>输入问题，邀请专家库进行讨论</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">你</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">专家委员会</div>

                  {/* Stage 0 */}
                  {msg.loading?.stage0 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 0 进行中：文档预处理...</span>
                    </div>
                  )}
                  {msg.stage0 && <Stage0 preprocess={msg.stage0} />}

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 1 进行中：收集各专家初稿...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 2 进行中：互评与排名...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToAgent={msg.metadata?.label_to_agent}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Stage 2B */}
                  {msg.loading?.stage2b && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 2B 进行中：圆桌讨论...</span>
                    </div>
                  )}
                  {msg.stage2b && <Stage2b messages={msg.stage2b} />}

                  {/* Stage 2C */}
                  {msg.loading?.stage2c && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 2C 进行中：事实核查与证据整理...</span>
                    </div>
                  )}
                  {msg.stage2c && <Stage2c factCheck={msg.stage2c} />}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 3 进行中：主席综合结论...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}

                  {/* Stage 4 */}
                  {msg.loading?.stage4 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>阶段 4 进行中：主席撰写完整报告...</span>
                    </div>
                  )}
                  {msg.stage4 && <Stage4 report={msg.stage4} />}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>专家讨论中...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        <textarea
          className="message-input"
          placeholder="输入你的问题...（Shift+Enter 换行，Enter 发送）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          rows={3}
        />
        <button type="submit" className="send-button" disabled={!input.trim() || isLoading}>
          发送
        </button>
      </form>
    </div>
  );
}
