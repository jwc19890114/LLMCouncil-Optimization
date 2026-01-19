import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function unwrapWholeMarkdownFence(input) {
  const text = String(input ?? '');
  const trimmed = text.trim();
  const m = trimmed.match(/^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$/i);
  if (!m) return text;
  return String(m[1] ?? '').trim();
}

export default function Markdown({ children }) {
  const text = unwrapWholeMarkdownFence(children);
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>;
}

