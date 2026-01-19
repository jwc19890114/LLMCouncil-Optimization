import React from 'react';
import Markdown from './Markdown';
import './Stage2b.css';

function initials(name) {
  const n = String(name || '').trim();
  if (!n) return 'A';
  const ascii = n.replace(/[^\x00-\x7F]/g, '').trim();
  if (ascii) return ascii.slice(0, 2).toUpperCase();
  return n.slice(0, 1);
}

function hashColor(input) {
  const s = String(input || '');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  return `hsl(${hue} 70% 45%)`;
}

function isSystemLikeMessage(m) {
  const name = String(m?.agent_name || '').toLowerCase();
  const id = String(m?.agent_id || '').trim();
  const msg = String(m?.message || '').trim();
  if (!id && name.includes('chairman')) return true;
  if (name === 'chairman') return true;
  if (msg.startsWith('（已切换剧本') || msg.startsWith('(已切换剧本')) return true;
  return false;
}

export default function Stage2b({ messages, mode = '', livelyMeta = null }) {
  const list = Array.isArray(messages) ? messages : [];
  if (list.length === 0) return null;

  const isLively = String(mode || '').toLowerCase() === 'lively' || Boolean(livelyMeta);
  const script = livelyMeta?.script || '';
  const turnsUsed = livelyMeta?.turns_used;
  const messagesUsed = livelyMeta?.messages_used;

  return (
    <div className="stage2b stage2b-chat">
      <div className="stage2b-header">
        <div className="stage2b-title">{isLively ? '阶段 2B：活力群聊' : '阶段 2B：圆桌讨论'}</div>
        {isLively ? (
          <div className="stage2b-subtitle">
            {script ? `剧本：${script}` : ''}
            {typeof turnsUsed === 'number' ? ` · 轮次：${turnsUsed}` : ''}
            {typeof messagesUsed === 'number' ? ` · 消息：${messagesUsed}` : ''}
          </div>
        ) : null}
      </div>

      <div className="stage2b-chatlist">
        {list.map((m, idx) => {
          const key = `${m.agent_id || m.agent_name || 'msg'}-${idx}`;
          const name = m.agent_name || 'Agent';
          const model = m.model || '';
          const systemLike = isSystemLikeMessage(m);
          const avatarSeed = m.agent_id || name;
          const avatarBg = hashColor(avatarSeed);

          if (systemLike) {
            return (
              <div key={key} className="stage2b-system">
                <div className="stage2b-system-badge">{name}</div>
                <div className="stage2b-system-bubble">
                  <Markdown>{m.message || ''}</Markdown>
                </div>
              </div>
            );
          }

          return (
            <div key={key} className="stage2b-msg">
              <div className="stage2b-avatar" style={{ background: avatarBg }} title={model || ''}>
                {initials(name)}
              </div>
              <div className="stage2b-msg-main">
                <div className="stage2b-msg-meta">
                  <span className="stage2b-msg-name">{name}</span>
                  {model ? <span className="stage2b-msg-model">{model}</span> : null}
                </div>
                <div className="stage2b-bubble">
                  <Markdown>{m.message || ''}</Markdown>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

