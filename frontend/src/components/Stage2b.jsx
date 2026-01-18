import React from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage2b.css';

export default function Stage2b({ messages }) {
  const list = Array.isArray(messages) ? messages : [];
  if (list.length === 0) return null;

  return (
    <div className="stage2b">
      <div className="stage2b-title">阶段 2B：圆桌讨论</div>
      <div className="stage2b-list">
        {list.map((m, idx) => (
          <div key={`${m.agent_id || idx}`} className="stage2b-item">
            <div className="stage2b-meta">
              <span className="stage2b-name">{m.agent_name || 'Agent'}</span>
              {m.model ? <span className="stage2b-model">{m.model}</span> : null}
            </div>
            <div className="stage2b-content">
              <ReactMarkdown>{m.message || ''}</ReactMarkdown>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

