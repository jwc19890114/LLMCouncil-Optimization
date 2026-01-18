import { Component } from 'react';
import './ErrorBoundary.css';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('UI crashed:', error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    const message = this.state.error?.message || String(this.state.error || 'Unknown error');
    const stack = this.state.error?.stack || '';

    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <div className="error-boundary-title">页面发生错误</div>
          <div className="error-boundary-subtitle">
            这是前端运行时异常导致的白屏保护。请刷新页面，或在浏览器控制台查看详细错误。
          </div>
          <div className="error-boundary-actions">
            <button className="error-boundary-btn primary" onClick={() => window.location.reload()}>
              刷新页面
            </button>
          </div>
          <div className="error-boundary-pre">
            <div className="error-boundary-pre-title">错误信息</div>
            <pre>{message}</pre>
            {stack ? (
              <>
                <div className="error-boundary-pre-title">Stack</div>
                <pre>{stack}</pre>
              </>
            ) : null}
          </div>
        </div>
      </div>
    );
  }
}

