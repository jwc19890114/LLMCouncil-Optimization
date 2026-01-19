import { useState } from 'react';
import Markdown from './Markdown';
import './Stage2.css';

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

function deAnonymizeText(text, labelToAgent) {
  if (!labelToAgent) return text;

  let result = text;
  // Replace each "Response X" with the expert name
  Object.entries(labelToAgent).forEach(([label, meta]) => {
    const display = meta?.agent_name || meta?.model_spec || label;
    result = result.replace(new RegExp(label, 'g'), `**${display}**`);
  });
  return result;
}

export default function Stage2({ rankings, labelToAgent, aggregateRankings }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!rankings || rankings.length === 0) {
    return null;
  }

  return (
    <div className="stage stage2">
      <h3 className="stage-title">阶段 2：互评与排名</h3>

      <h4>评审原文</h4>
      <p className="stage-description">
        每位专家会对所有回答进行评审（评审时使用 Response A/B/C... 的匿名代号），并在末尾给出最终排名。
        下面会把匿名代号替换为专家名称，便于阅读与导出分析。
      </p>

      <div className="tabs">
        {rankings.map((rank, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {shortLabel(rank.model, rank.agent_name)}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="ranking-model">
          {rankings[activeTab].agent_name ? `${rankings[activeTab].agent_name} · ` : ''}
          {rankings[activeTab].model}
        </div>
        <div className="ranking-content markdown-content">
          <Markdown>{deAnonymizeText(rankings[activeTab].ranking, labelToAgent)}</Markdown>
        </div>

        {rankings[activeTab].parsed_ranking &&
         rankings[activeTab].parsed_ranking.length > 0 && (
          <div className="parsed-ranking">
            <strong>解析出的最终排名：</strong>
            <ol>
              {rankings[activeTab].parsed_ranking.map((label, i) => (
                <li key={i}>
                  {labelToAgent && labelToAgent[label]
                    ? labelToAgent[label].agent_name || labelToAgent[label].model_spec || label
                    : label}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      {aggregateRankings && aggregateRankings.length > 0 && (
        <div className="aggregate-rankings">
          <h4>聚合排名（加权）</h4>
          <p className="stage-description">
            汇总所有评审的结果（分数越低越好）：
          </p>
          <div className="aggregate-list">
            {aggregateRankings.map((agg, index) => (
              <div key={index} className="aggregate-item">
                <span className="rank-position">#{index + 1}</span>
                <span className="rank-model">
                  {shortLabel(agg.model)}
                </span>
                <span className="rank-score">
                  均值: {agg.average_rank.toFixed(2)}
                </span>
                <span className="rank-count">({agg.votes ?? agg.rankings_count ?? 0} 票)</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
