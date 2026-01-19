import { useState, useEffect, useMemo, useRef } from 'react';
import { api } from '../api';
import Markdown from './Markdown';
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
  const [isDiscussionOpen, setIsDiscussionOpen] = useState(false);
  const [discussionDraft, setDiscussionDraft] = useState(null);
  const [isJobsOpen, setIsJobsOpen] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [jobsError, setJobsError] = useState('');
  const [isEvidenceOpen, setIsEvidenceOpen] = useState(false);
  const [evidenceQuery, setEvidenceQuery] = useState('');
  const [evidenceMode, setEvidenceMode] = useState('evidence_pack'); // web_search | evidence_pack
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

  useEffect(() => {
    if (!isJobsOpen) return;
    if (!conversation?.id) return;
    let cancelled = false;
    setJobsError('');
    api
      .listJobs({ conversation_id: conversation.id, limit: 50 })
      .then((r) => {
        if (cancelled) return;
        setJobs(r?.jobs || []);
      })
      .catch((e) => {
        if (cancelled) return;
        setJobsError(e?.message || '加载任务失败');
      });
    const timer = setInterval(() => {
      api
        .listJobs({ conversation_id: conversation.id, limit: 50 })
        .then((r) => {
          if (cancelled) return;
          setJobs(r?.jobs || []);
        })
        .catch(() => {});
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isJobsOpen, conversation?.id]);

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
          <h2>欢迎使用 SynthesisLab</h2>
          <p>请先新建一个会话开始</p>
        </div>
      </div>
    );
  }

  async function handleUploadFile(file) {
    if (!conversation?.id || !file) return;
    setUploadError('');
    setUploadNotice('');
    setIsUploading(true);
    try {
      const sizeLimit = 20 * 1024 * 1024;
      if (file.size > sizeLimit) {
        throw new Error('文件过大（限制 20MB），请先裁剪后再上传');
      }

      const title = file.name || 'uploaded';
      const source = `upload:${title}`;

      const form = new FormData();
      form.append('file', file);
      form.append('conversation_id', conversation.id);
      form.append('title', title);
      form.append('source', source);
      form.append('categories_json', JSON.stringify(['upload']));
      form.append('agent_ids_json', JSON.stringify([]));

      const created = await api.uploadKBDocumentFile(form);
      const docId = created?.doc_id;
      if (!docId) throw new Error('上传失败：未返回 doc_id');

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
            accept=".txt,.md,.json,.csv,.docx,.xlsx,text/*"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUploadFile(f);
            }}
          />
          <button
            className="toolbar-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || isUploading}
            title="上传文档并绑定到当前会话（支持 txt/md/docx/xlsx）"
          >
            {isUploading ? '上传中...' : '上传文档'}
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
          <button
            className="toolbar-btn"
            onClick={() => {
              setDiscussionDraft({
                discussion_mode: conversation?.discussion_mode || 'serious',
                serious_iteration_rounds: Number(conversation?.serious_iteration_rounds || 1),
                lively_script: conversation?.lively_script || 'groupchat',
                lively_max_messages: Number(conversation?.lively_max_messages || 24),
                lively_max_turns: Number(conversation?.lively_max_turns || 6),
              });
              setIsDiscussionOpen(true);
            }}
            disabled={isLoading || isUploading}
            title="设置严肃/活力讨论模式与轮数/剧本/安全上限"
          >
            讨论模式
          </button>
          <button className="toolbar-btn" onClick={() => setIsJobsOpen(true)} disabled={isLoading || isUploading}>
            任务
          </button>
          <button
            className="toolbar-btn"
            onClick={() => {
              setEvidenceQuery('');
              setEvidenceMode('evidence_pack');
              setIsEvidenceOpen(true);
            }}
            disabled={isLoading || isUploading}
          >
            证据
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

      {isDiscussionOpen && discussionDraft && (
        <div className="chat-modal-overlay" onClick={() => setIsDiscussionOpen(false)}>
          <div className="chat-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chat-modal-header">
              <div className="chat-modal-title">讨论模式（本会话）</div>
              <button className="chat-modal-close" onClick={() => setIsDiscussionOpen(false)}>
                ✕
              </button>
            </div>
            <div className="chat-modal-body">
              <div className="chat-modal-hint">
                严肃模式：按“报告迭代轮数”自动多轮讨论并产出最终报告。活力模式：自由流群聊，Chairman 可中途切换剧本，但受安全上限约束。
              </div>

              <div className="chat-modal-row">
                <div className="chat-modal-label">模式</div>
                <select
                  className="chat-modal-input"
                  value={discussionDraft.discussion_mode || 'serious'}
                  onChange={(e) =>
                    setDiscussionDraft((p) => ({ ...p, discussion_mode: e.target.value || 'serious' }))
                  }
                >
                  <option value="serious">严肃模式（报告迭代）</option>
                  <option value="lively">活力模式（自由流群聊）</option>
                </select>
              </div>

              <div className="chat-modal-row">
                <div className="chat-modal-label">报告迭代轮数</div>
                <select
                  className="chat-modal-input"
                  value={Math.max(1, Math.min(8, Number(discussionDraft.serious_iteration_rounds || 1)))}
                  onChange={(e) =>
                    setDiscussionDraft((p) => ({
                      ...p,
                      serious_iteration_rounds: Math.max(1, Math.min(8, Number(e.target.value || 1))),
                    }))
                  }
                  disabled={discussionDraft.discussion_mode !== 'serious'}
                >
                  {Array.from({ length: 8 }).map((_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1}
                    </option>
                  ))}
                </select>
              </div>

              <div className="chat-modal-row">
                <div className="chat-modal-label">活力剧本</div>
                <select
                  className="chat-modal-input"
                  value={discussionDraft.lively_script || 'groupchat'}
                  onChange={(e) =>
                    setDiscussionDraft((p) => ({ ...p, lively_script: e.target.value || 'groupchat' }))
                  }
                  disabled={discussionDraft.discussion_mode !== 'lively'}
                >
                  <option value="groupchat">普通群聊</option>
                  <option value="brainstorm">头脑风暴</option>
                  <option value="interview">角色扮演采访</option>
                </select>
              </div>

              <div className="chat-modal-row">
                <div className="chat-modal-label">最大消息数</div>
                <input
                  className="chat-modal-input"
                  type="number"
                  value={Math.max(6, Math.min(200, Number(discussionDraft.lively_max_messages || 24)))}
                  onChange={(e) =>
                    setDiscussionDraft((p) => ({
                      ...p,
                      lively_max_messages: Math.max(6, Math.min(200, Number(e.target.value || 24))),
                    }))
                  }
                  disabled={discussionDraft.discussion_mode !== 'lively'}
                />
              </div>

              <div className="chat-modal-row">
                <div className="chat-modal-label">最大轮次</div>
                <input
                  className="chat-modal-input"
                  type="number"
                  value={Math.max(1, Math.min(50, Number(discussionDraft.lively_max_turns || 6)))}
                  onChange={(e) =>
                    setDiscussionDraft((p) => ({
                      ...p,
                      lively_max_turns: Math.max(1, Math.min(50, Number(e.target.value || 6))),
                    }))
                  }
                  disabled={discussionDraft.discussion_mode !== 'lively'}
                />
              </div>
            </div>
            <div className="chat-modal-actions">
              <button className="toolbar-btn" onClick={() => setIsDiscussionOpen(false)} disabled={isLoading}>
                取消
              </button>
              <button
                className="toolbar-btn primary"
                onClick={async () => {
                  try {
                    await api.setConversationDiscussion(conversation.id, discussionDraft);
                    await onRefreshConversation?.();
                    setIsDiscussionOpen(false);
                  } catch (err) {
                    setUploadError(err?.message || '设置讨论模式失败');
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

      {isJobsOpen && (
        <div className="chat-modal-overlay" onClick={() => setIsJobsOpen(false)}>
          <div className="chat-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chat-modal-header">
              <div className="chat-modal-title">后台任务（Jobs）</div>
              <button className="chat-modal-close" onClick={() => setIsJobsOpen(false)}>
                ✕
              </button>
            </div>
            <div className="chat-modal-body">
              {jobsError ? <div className="trace-error">{jobsError}</div> : null}
              {jobs.length === 0 ? (
                <div className="chat-modal-hint">暂无任务。</div>
              ) : (
                <div className="jobs-list">
                  {jobs.slice(0, 50).map((j) => (
                    <div key={j.id} className="jobs-item">
                      <div className="jobs-meta">
                        <span className="jobs-type">{j.job_type}</span>
                        <span className="jobs-status">{j.status}</span>
                        {typeof j.progress === 'number' ? (
                          <span className="jobs-progress">{Math.round(j.progress * 100)}%</span>
                        ) : null}
                      </div>
                      {j.result?.summary ? <div className="jobs-summary">{j.result.summary}</div> : null}
                      {j.error ? <div className="trace-errorline">{j.error}</div> : null}
                      {j.status === 'queued' || j.status === 'running' ? (
                        <button
                          className="toolbar-btn"
                          onClick={async () => {
                            try {
                              await api.cancelJob(j.id);
                            } catch (e) {
                              setJobsError(e?.message || '取消任务失败');
                            }
                          }}
                        >
                          取消
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {isEvidenceOpen && (
        <div className="chat-modal-overlay" onClick={() => setIsEvidenceOpen(false)}>
          <div className="chat-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chat-modal-header">
              <div className="chat-modal-title">网页检索 / 证据整理</div>
              <button className="chat-modal-close" onClick={() => setIsEvidenceOpen(false)}>
                ✕
              </button>
            </div>
            <div className="chat-modal-body">
              <div className="chat-modal-hint">
                网页检索：只拉取网页列表。证据整理：网页 + 当前会话已绑定的 KB 文档（FTS）一起整理，结果会作为后台任务回填到下一轮讨论上下文。
              </div>
              <div className="chat-modal-row">
                <div className="chat-modal-label">模式</div>
                <select className="chat-modal-input" value={evidenceMode} onChange={(e) => setEvidenceMode(e.target.value)}>
                  <option value="evidence_pack">证据整理（网页+KB）</option>
                  <option value="web_search">网页检索</option>
                </select>
              </div>
              <div className="chat-modal-row">
                <div className="chat-modal-label">查询</div>
                <input
                  className="chat-modal-input"
                  value={evidenceQuery}
                  onChange={(e) => setEvidenceQuery(e.target.value)}
                  placeholder="输入要检索/整理证据的关键词或问题"
                />
              </div>
            </div>
            <div className="chat-modal-actions">
              <button className="toolbar-btn" onClick={() => setIsEvidenceOpen(false)} disabled={isLoading}>
                取消
              </button>
              <button
                className="toolbar-btn primary"
                onClick={async () => {
                  const q = String(evidenceQuery || '').trim();
                  if (!q) {
                    setUploadError('请输入查询内容');
                    return;
                  }
                  try {
                    await api.createJob({
                      job_type: evidenceMode,
                      conversation_id: conversation?.id || '',
                      payload:
                        evidenceMode === 'web_search'
                          ? { query: q, max_results: 5 }
                          : { query: q, max_web_results: 5, max_kb_chunks: 6 },
                    });
                    setIsEvidenceOpen(false);
                    setUploadNotice('已创建后台任务，完成后会自动回填到下一轮讨论上下文，可在“任务”中查看进度。');
                    setTimeout(() => setUploadNotice(''), 6000);
                  } catch (err) {
                    setUploadError(err?.message || '创建任务失败');
                  }
                }}
                disabled={isLoading}
              >
                开始
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
                      <Markdown>{msg.content}</Markdown>
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
                        <Markdown>{msg.direct.content || ''}</Markdown>
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
                  {msg.stage2b && (
                    <Stage2b
                      messages={msg.stage2b}
                      mode={msg.metadata?.discussion_mode || ''}
                      livelyMeta={msg.metadata?.lively || null}
                    />
                  )}

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
                  {msg.stage4 && <Stage4 report={msg.stage4} conversationId={conversation.id} onSaved={onRefreshConversation} />}
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
