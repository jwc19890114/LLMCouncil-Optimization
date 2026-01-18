import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage1.css';

function shortLabel(modelSpec, agentName) {
  if (agentName) return agentName;
  if (!modelSpec) return '';
  if (modelSpec.includes(':')) {
    const [provider, model] = modelSpec.split(':', 2);
    const short = model.split('/')[1] || model;
    return `${provider}:${short}`;
  }
  return modelSpec.split('/')[1] || modelSpec;
}

export default function Stage1({ responses }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!responses || responses.length === 0) {
    return null;
  }

  return (
    <div className="stage stage1">
      <h3 className="stage-title">阶段 1：各专家初稿</h3>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {shortLabel(resp.model, resp.agent_name)}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="model-name">
          {responses[activeTab].agent_name ? `${responses[activeTab].agent_name} · ` : ''}
          {responses[activeTab].model}
        </div>
        <div className="response-text markdown-content">
          <ReactMarkdown>{responses[activeTab].response}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
