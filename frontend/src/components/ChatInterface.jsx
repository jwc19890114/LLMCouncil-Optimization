import { useState, useEffect, useMemo, useRef } from 'react';
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
  allAgents,
  chairmanOptions,
  defaultChairmanLabel,
}) {
  const [input, setInput] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [uploadNotice, setUploadNotice] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isInvoking, setIsInvoking] = useState(false);
  const [isReportReqOpen, setIsReportReqOpen] = useState(false);
  const [reportRequirementsDraft, setReportRequirementsDraft] = useState('');
  const [trace, setTrace] = useState([]);
  const [showTrace, setShowTrace] = useState(false);
  const [traceError, setTraceError] = useState('');
  const [expandedTraceIndex, setExpandedTraceIndex] = useState(null);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashItems, setSlashItems] = useState([]);
  const [slashIndex, setSlashIndex] = useState(0);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const enabledAgents = useMemo(
    () => (Array.isArray(allAgents) ? allAgents.filter((a) => a?.enabled) : []),
    [allAgents]
  );
  const selectedIds = useMemo(
    () => (Array.isArray(conversation?.agent_ids) ? conversation.agent_ids : null),
    [conversation?.agent_ids]
  );
  const groupAgents = useMemo(
    () => (selectedIds ? enabledAgents.filter((a) => selectedIds.includes(a.id)) : enabledAgents),
    [selectedIds, enabledAgents]
  );

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

  function parseSlashContext(text) {
    const v = String(text || '');
    const caretLine = v.split('\n').slice(-1)[0] || '';
    if (!caretLine.startsWith('/')) return null;
    const raw = caretLine.slice(1);
    const tokens = raw.split(/\s+/).filter((t) => t.length > 0);
    return { line: caretLine, raw, tokens };
  }

  function applySlashItem(ctx, item) {
    const full = String(input || '');
    const lines = full.split('\n');
    const last = lines[lines.length - 1] || '';
    if (!last.startsWith('/')) return;

    if (item.type === 'command') {
      lines[lines.length - 1] = `/${item.key} `;
      setInput(lines.join('\n'));
      return;
    }

    if (item.type === 'agent') {
      lines[lines.length - 1] = `/ask ${item.agent.id} `;
      setInput(lines.join('\n'));
      return;
    }

    if (item.type === 'invite') {
      lines[lines.length - 1] = `/add ${item.agent.id} `;
      setInput(lines.join('\n'));
      return;
    }

    if (item.type === 'agent_for_cmd') {
      const cmd = item.command;
      const rest = ctx.tokens.slice(2).join(' ');
      lines[lines.length - 1] = `/${cmd} ${item.agent.id}${rest ? ` ${rest}` : ' '}`;
      setInput(lines.join('\n'));
      return;
    }
  }

  useEffect(() => {
    const ctx = parseSlashContext(input);
    if (!ctx) {
      setSlashOpen(false);
      setSlashItems([]);
      setSlashIndex(0);
      return;
    }

    const items = [];
    const token0 = ctx.tokens?.[0] || '';
    const token1 = ctx.tokens?.[1] || '';

    const commands = [
      { key: 'ask', label: 'ask（让某个 Agent 单独回答）' },
      { key: 'report', label: 'report（让某个 Agent 单独撰写报告）' },
      { key: 'add', label: 'add（把某个 Agent 拉进本会话）' },
    ];

    if (ctx.tokens.length <= 1) {
      for (const c of commands) {
        if (!token0 || c.key.startsWith(token0.toLowerCase())) {
          items.push({ type: 'command', key: c.key, label: `/${c.key} …` });
        }
      }
      for (const a of groupAgents) {
        const name = String(a?.name || '');
        if (!token0 || name.toLowerCase().includes(token0.toLowerCase())) {
          items.push({ type: 'agent', key: a.id, label: `${name}（组内）`, agent: a });
        }
      }
      for (const a of enabledAgents) {
        if (selectedIds && selectedIds.includes(a.id)) continue;
        const name = String(a?.name || '');
        if (!token0 || name.toLowerCase().includes(token0.toLowerCase())) {
          items.push({ type: 'invite', key: a.id, label: `${name}（可邀请）`, agent: a });
        }
      }
      items.splice(16);
    } else if (['ask', 'report', 'add'].includes(token0.toLowerCase())) {
      const cmd = token0.toLowerCase();
      const pool = cmd === 'add' ? enabledAgents : groupAgents;
      for (const a of pool) {
        const name = String(a?.name || '');
        if (
          !token1 ||
          name.toLowerCase().includes(token1.toLowerCase()) ||
          String(a.id).startsWith(token1)
        ) {
          items.push({
            type: 'agent_for_cmd',
            key: a.id,
            label: `${name} (${a.id})`,
            agent: a,
            command: cmd,
          });
        }
      }
      items.splice(16);
    }

    setSlashItems(items);
    setSlashOpen(items.length > 0);
    setSlashIndex(0);
  }, [input, enabledAgents, groupAgents, selectedIds]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const raw = (input || '').trim();
    if (!raw || isLoading || isUploading || isInvoking) return;

    if (raw.startsWith('/')) {
      const ctx = parseSlashContext(raw);
      const tokens = (ctx?.tokens || []).slice();
      const token0 = (tokens[0] || '').toLowerCase();
      let action = token0;
      let agentToken = tokens[1] || '';
      let rest = tokens.slice(2).join(' ');

      if (!['ask', 'report', 'add'].includes(action)) {
        agentToken = tokens[0] || '';
        rest = tokens.slice(1).join(' ');
        action = 'ask';
      }

      const findAgent = (t) => {
        const s = String(t || '').trim();
        if (!s) return null;
        const byId = enabledAgents.find((a) => a.id === s);
        if (byId) return byId;
        const byName = enabledAgents.find((a) => String(a.name || '').trim() === s);
        if (byName) return byName;
        return null;
      };

      const agent = findAgent(agentToken);
      if (!agent) {
        setUploadError('未找到该 Agent（请在 “/” 下拉中选择）');
        return;
      }

      (async () => {
        setIsInvoking(true);
        setUploadError('');
        try {
          if (action === 'add') {
            const current = Array.isArray(conversation?.agent_ids) ? conversation.agent_ids : null;
            const base = current ? [...current] : enabledAgents.map((a) => a.id);
            const next = Array.from(new Set([...base, agent.id]));
            await api.setConversationAgents(conversation.id, next);
            await onRefreshConversation?.();
            setInput('');
            setUploadNotice(`已将 ${agent.name} 拉入本会话。你可以继续输入你的要求并发送。`);
            setTimeout(() => setUploadNotice(''), 6000);
            return;
          }

          if (action === 'report') {
            let topic = '';
            let reportReq = rest;
            if (rest.includes('||')) {
              const [a, b] = rest.split('||');
              topic = (a || '').trim();
              reportReq = (b || '').trim();
            }
            await api.invokeConversationAgent(conversation.id, {
              action: 'report',
              agent_id: agent.id,
              content: topic,
              report_requirements: reportReq,
            });
            await onRefreshConversation?.();
            setInput('');
            return;
          }

          if (!rest.trim()) {
            setUploadError('请输入要让该 Agent 完成的任务内容');
            return;
          }
          await api.invokeConversationAgent(conversation.id, {
            action: 'ask',
            agent_id: agent.id,
            content: rest,
          });
          await onRefreshConversation?.();
          setInput('');
        } catch (err) {
          setUploadError(err?.message || '执行失败');
        } finally {
          setIsInvoking(false);
        }
      })();
      return;
    }

    onSendMessage(input);
    setInput('');
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
    setUploadNotice('');
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

      setUploadNotice(`已上传并绑定到当前会话：${title}。你可以继续补充你的讨论要求后再发送。`);
      const template =
        `基于我上传的背景资料《${title}》，请按以下要求进行讨论与解读：\n` +
        `1) \n` +
        `2) \n` +
        `3) \n`;
      setInput((prev) => {
        const cur = (prev || '').trim();
        if (!cur) return template;
        return `${cur}\n\n${template}`;
      });
    } catch (e) {
      setUploadError(e?.message || '上传失败');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setTimeout(() => setUploadNotice(''), 6000);
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

      {uploadNotice ? <div className="chat-notice">{uploadNotice}</div> : null}

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

                  {msg.direct ? (
                    <div className="stage2b" style={{ marginTop: 0 }}>
                      <div className="stage2b-title">
                        单独发言：{msg.direct.agent_name || 'Agent'}
                      </div>
                      <div className="stage2b-content">
                        <ReactMarkdown>{msg.direct.content || ''}</ReactMarkdown>
                      </div>
                    </div>
                  ) : null}

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
          onKeyDown={(e) => {
            if (slashOpen) {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSlashIndex((i) => Math.min(i + 1, slashItems.length - 1));
                return;
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSlashIndex((i) => Math.max(i - 1, 0));
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                setSlashOpen(false);
                return;
              }
              if (e.key === 'Tab') {
                const ctx = parseSlashContext(input);
                const item = slashItems[slashIndex];
                if (ctx && item) {
                  e.preventDefault();
                  applySlashItem(ctx, item);
                  return;
                }
              }
              if (e.key === 'Enter' && slashItems[slashIndex]) {
                const ctx = parseSlashContext(input);
                if (ctx && ctx.tokens.length <= 2) {
                  e.preventDefault();
                  applySlashItem(ctx, slashItems[slashIndex]);
                  return;
                }
              }
            }
            handleKeyDown(e);
          }}
          disabled={isLoading || isInvoking}
          rows={3}
        />
        {slashOpen && slashItems.length > 0 && (
          <div className="slash-menu">
            {slashItems.map((it, idx) => (
              <button
                key={`${it.type}-${it.key}-${idx}`}
                type="button"
                className={`slash-item ${idx === slashIndex ? 'on' : ''}`}
                onClick={() => {
                  const ctx = parseSlashContext(input);
                  if (!ctx) return;
                  applySlashItem(ctx, it);
                }}
              >
                {it.label}
              </button>
            ))}
          </div>
        )}
        <button
          type="submit"
          className="send-button"
          disabled={!input.trim() || isLoading || isUploading || isInvoking}
        >
          发送
        </button>
      </form>
    </div>
  );
}
