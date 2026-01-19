import { useState } from 'react';
import { api } from '../api';
import Markdown from './Markdown';
import './Stage4.css';

export default function Stage4({ report, conversationId = '', onSaved }) {
  if (!report) return null;
  const markdown = report.report_markdown || '';
  const kbDocId = report.kb_doc_id || '';
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  return (
    <div className="stage4">
      <div className="stage4-title">阶段 4：完整报告（Chairman）</div>
      {kbDocId ? <div className="stage4-meta">已落盘到知识库：{kbDocId}</div> : null}
      {!kbDocId && conversationId ? (
        <div className="stage4-meta">
          <button
            className="stage4-btn"
            disabled={saving}
            onClick={async () => {
              setSaveError('');
              setSaving(true);
              try {
                await api.saveConversationReportToKB(conversationId);
                if (typeof onSaved === 'function') await onSaved();
                else window.location.reload();
              } catch (e) {
                setSaveError(e?.message || '保存失败');
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? '保存中...' : '保存到知识库'}
          </button>
          {saveError ? <span style={{ marginLeft: 10, color: '#c00' }}>{saveError}</span> : null}
        </div>
      ) : null}
      <div className="stage4-content">
        <Markdown>{markdown}</Markdown>
      </div>
    </div>
  );
}
