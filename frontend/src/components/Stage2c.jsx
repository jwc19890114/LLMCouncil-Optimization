import React from 'react';
import './Stage2c.css';

export default function Stage2c({ factCheck }) {
  if (!factCheck) return null;
  return (
    <div className="stage2c">
      <div className="stage2c-title">阶段 2C：事实核查（结构化 JSON）</div>
      <pre className="stage2c-pre">{JSON.stringify(factCheck, null, 2)}</pre>
    </div>
  );
}

