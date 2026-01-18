import React from 'react';
import './Stage0.css';

function renderList(items) {
  const arr = Array.isArray(items) ? items : [];
  if (arr.length === 0) return null;
  return (
    <ul className="stage0-list">
      {arr.slice(0, 8).map((x, i) => (
        <li key={i}>{String(x || '').trim()}</li>
      ))}
    </ul>
  );
}

export default function Stage0({ preprocess }) {
  if (!preprocess) return null;
  const summary = String(preprocess.summary || '').trim();
  const outline = preprocess.outline;
  const keyQuestions = preprocess.key_questions;
  const subtasks = preprocess.suggested_subtasks;
  const usedDocs = Array.isArray(preprocess.used_docs) ? preprocess.used_docs : [];

  return (
    <div className="stage0">
      <div className="stage0-title">阶段 0：文档预处理</div>
      {summary ? <div className="stage0-summary">{summary}</div> : null}

      {renderList(keyQuestions) ? (
        <div className="stage0-block">
          <div className="stage0-label">关键问题</div>
          {renderList(keyQuestions)}
        </div>
      ) : null}

      {renderList(subtasks) ? (
        <div className="stage0-block">
          <div className="stage0-label">建议拆分任务</div>
          {renderList(subtasks)}
        </div>
      ) : null}

      {renderList(outline) ? (
        <div className="stage0-block">
          <div className="stage0-label">文档大纲（推测）</div>
          {renderList(outline)}
        </div>
      ) : null}

      {usedDocs.length > 0 ? (
        <div className="stage0-useddocs">涉及文档：{usedDocs.slice(0, 12).join('，')}</div>
      ) : null}
    </div>
  );
}

