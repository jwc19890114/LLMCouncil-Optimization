import React from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage4.css';

export default function Stage4({ report }) {
  if (!report) return null;
  const markdown = report.report_markdown || '';
  const kbDocId = report.kb_doc_id || '';

  return (
    <div className="stage4">
      <div className="stage4-title">阶段 4：完整报告（Chairman）</div>
      {kbDocId ? <div className="stage4-meta">已落盘到知识库：{kbDocId}</div> : null}
      <div className="stage4-content">
        <ReactMarkdown>{markdown}</ReactMarkdown>
      </div>
    </div>
  );
}

