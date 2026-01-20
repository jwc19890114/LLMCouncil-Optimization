import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import AgentsModal from './components/AgentsModal';
import ConversationAgentsModal from './components/ConversationAgentsModal';
import KnowledgeBasePage from './components/KnowledgeBasePage';
import GraphPage from './components/GraphPage';
import SettingsModal from './components/SettingsModal';
import PluginsPage from './components/PluginsPage';
import { api } from './api';
import './App.css';

const API_BASE =
  import.meta.env.VITE_API_BASE ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8001');

function App() {
  const [conversations, setConversations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const streamAbortRef = useRef(null);
  const [status, setStatus] = useState(null);
  const [isAgentsOpen, setIsAgentsOpen] = useState(false);
  const [isConversationAgentsOpen, setIsConversationAgentsOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [activeView, setActiveView] = useState('chat'); // chat | kb | graph | plugins

  async function loadConversations() {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  }

  async function loadStatus() {
    try {
      const s = await api.getStatus();
      setStatus(s);
    } catch (error) {
      console.error('Failed to load status:', error);
    }
  }

  async function loadProjects() {
    try {
      const ps = await api.listProjects();
      setProjects(ps);
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  }

  // Load conversations on mount
  useEffect(() => {
    let cancelled = false;

    api
      .listConversations()
      .then((convs) => {
        if (!cancelled) setConversations(convs);
      })
      .catch((error) => {
        console.error('Failed to load conversations:', error);
      });

    api
      .getStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((error) => {
        console.error('Failed to load status:', error);
      });

    api
      .listProjects()
      .then((ps) => {
        if (!cancelled) setProjects(ps);
      })
      .catch((error) => {
        console.error('Failed to load projects:', error);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (!currentConversationId) return;

    let cancelled = false;

    api
      .getConversation(currentConversationId)
      .then((conv) => {
        if (!cancelled) setCurrentConversation(conv);
      })
      .catch((error) => {
        console.error('Failed to load conversation:', error);
      });

    return () => {
      cancelled = true;
    };
  }, [currentConversationId]);

  // Stream job updates (no WebSocket): append chat-visible job messages into current conversation.
  useEffect(() => {
    if (!currentConversationId) return;
    if (activeView !== 'chat') return;

    const url = `${API_BASE}/api/conversations/${encodeURIComponent(currentConversationId)}/jobs/stream`;
    const es = new EventSource(url);

    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev?.data || '{}');
        const msg = payload?.message;
        const meta = msg?.metadata;
        if (!msg || meta?.type !== 'job_event') return;

        setCurrentConversation((prev) => {
          if (!prev || prev.id !== currentConversationId) return prev;
          const messages = Array.isArray(prev.messages) ? [...prev.messages] : [];
          const jobId = String(meta.job_id || '').trim();
          const status = String(meta.status || '').trim();
          if (jobId) {
            const exists = messages
              .slice(-80)
              .some(
                (m) =>
                  m?.metadata?.type === 'job_event' &&
                  String(m?.metadata?.job_id || '').trim() === jobId &&
                  String(m?.metadata?.status || '').trim() === status
              );
            if (exists) return prev;
          }
          messages.push(msg);
          return { ...prev, messages };
        });
      } catch (e) {
        // ignore parse errors
      }
    };

    return () => {
      try {
        es.close();
      } catch {
        // ignore
      }
    };
  }, [currentConversationId, activeView]);

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations((prev) => [
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...prev,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setActiveView('chat');
  };

  function downloadJson(filename, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: 'application/json;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  const handleExportConversation = async (id) => {
    try {
      const data = await api.exportConversation(id);
      const title = data?.conversation?.title || id;
      downloadJson(`synthesislab-${title}-${id}.json`, data);
    } catch (error) {
      console.error('Failed to export conversation:', error);
      alert(`导出失败：${error?.message || error}`);
    }
  };

  const handleDeleteConversation = async (id) => {
    if (!confirm('确定删除这条会话吗？（会同时删除 trace）')) return;
    try {
      await api.deleteConversation(id);
      await loadConversations();
      if (currentConversationId === id) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      alert(`删除失败：${error?.message || error}`);
    }
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    // Interrupt previous in-flight stream if any.
    try {
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
        streamAbortRef.current = null;
      }
    } catch {
      // ignore
    }

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage0: null,
        stage1: null,
        stage2: null,
        stage2b: null,
        stage2c: null,
        stage3: null,
        stage4: null,
        metadata: null,
        loading: {
          stage0: false,
          stage1: false,
          stage2: false,
          stage2b: false,
          stage2c: false,
          stage3: false,
          stage4: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

        // Send message with streaming
        const controller = new AbortController();
        streamAbortRef.current = controller;
        await api.sendMessageStream(
          currentConversationId,
          content,
          (eventType, event) => {
          switch (eventType) {
            case 'stage0_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage0 = true;
                return { ...prev, messages };
          },
          { signal: controller.signal }
        );
              break;

            case 'stage0_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage0 = event.data;
                lastMsg.loading.stage0 = false;
                return { ...prev, messages };
              });
              break;

            case 'stage1_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage1 = true;
                return { ...prev, messages };
              });
              break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

            case 'stage2_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage2 = event.data;
                lastMsg.metadata = event.metadata;
                lastMsg.loading.stage2 = false;
                return { ...prev, messages };
              });
              break;

            case 'stage2b_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage2b = true;
                lastMsg.stage2b = [];
                lastMsg.metadata = { ...(lastMsg.metadata || {}), discussion_mode: event.mode || '' };
                return { ...prev, messages };
              });
              break;

            case 'stage2b_message':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                const arr = Array.isArray(lastMsg.stage2b) ? [...lastMsg.stage2b] : [];
                if (event?.data) {
                  const incoming = event.data;
                  const last = arr.length ? arr[arr.length - 1] : null;
                  const sameAsLast =
                    last &&
                    String(last.agent_id || '') === String(incoming.agent_id || '') &&
                    String(last.agent_name || '') === String(incoming.agent_name || '') &&
                    String(last.message || '') === String(incoming.message || '');
                  if (!sameAsLast) arr.push(incoming);
                }
                lastMsg.stage2b = arr;
                lastMsg.metadata = { ...(lastMsg.metadata || {}), discussion_mode: event.mode || (lastMsg.metadata || {}).discussion_mode || '' };
                return { ...prev, messages };
              });
              break;

            case 'stage2b_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage2b = event.data;
                lastMsg.loading.stage2b = false;
                lastMsg.metadata = { ...(lastMsg.metadata || {}), ...(event.metadata || {}), discussion_mode: event.mode || (lastMsg.metadata || {}).discussion_mode || '' };
                return { ...prev, messages };
              });
              break;

            case 'stage2c_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage2c = true;
                return { ...prev, messages };
              });
              break;

            case 'stage2c_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage2c = event.data;
                lastMsg.loading.stage2c = false;
                return { ...prev, messages };
              });
              break;

            case 'stage3_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

            case 'stage3_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage3 = event.data;
                lastMsg.loading.stage3 = false;
                return { ...prev, messages };
              });
              break;

            case 'stage4_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage4 = true;
                return { ...prev, messages };
              });
              break;

            case 'stage4_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage4 = event.data;
                lastMsg.loading.stage4 = false;
                return { ...prev, messages };
              });
              break;

          case 'title_complete':
            // Update current title immediately + refresh sidebar list.
            setCurrentConversation((prev) => {
              if (!prev) return prev;
              const t = event?.data?.title;
              if (!t) return prev;
              return { ...prev, title: t };
            });
            setConversations((prev) => {
              const t = event?.data?.title;
              if (!t) return prev;
              const id = currentConversationId;
              return Array.isArray(prev)
                ? prev.map((c) => (c?.id === id ? { ...c, title: t } : c))
                : prev;
            });
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            loadStatus();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      });
    } catch (error) {
      if (error?.name === 'AbortError') {
        setIsLoading(false);
        return;
      }
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    } finally {
      streamAbortRef.current = null;
    }
  };

  const handleInterrupt = () => {
    try {
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
        streamAbortRef.current = null;
      }
    } catch {
      // ignore
    }
    setIsLoading(false);
  };

  const handleCreateProject = async (name) => {
    const n = String(name || '').trim();
    if (!n) return;
    try {
      await api.createProject({ name: n });
      await loadProjects();
    } catch (err) {
      console.error('Failed to create project:', err);
      alert(String(err?.message || err));
    }
  };

  const handleSetConversationArchived = async (conversationId, archived) => {
    const cid = String(conversationId || '').trim();
    if (!cid) return;
    try {
      await api.setConversationArchived(cid, !!archived);
      await loadConversations();
      if (currentConversationId === cid) {
        const c = await api.getConversation(cid);
        setCurrentConversation(c);
      }
    } catch (err) {
      console.error('Failed to update archive status:', err);
      alert(String(err?.message || err));
    }
  };

  const handleSetConversationProject = async (conversationId, projectId) => {
    const cid = String(conversationId || '').trim();
    if (!cid) return;
    try {
      await api.setConversationProject(cid, projectId || '');
      await loadConversations();
      if (currentConversationId === cid) {
        const c = await api.getConversation(cid);
        setCurrentConversation(c);
      }
    } catch (err) {
      console.error('Failed to set conversation project:', err);
      alert(String(err?.message || err));
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        projects={projects}
        status={status}
        currentConversationId={currentConversationId}
        currentConversation={currentConversation}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onDeleteConversation={handleDeleteConversation}
        onExportConversation={handleExportConversation}
        onCreateProject={handleCreateProject}
        onSetConversationArchived={handleSetConversationArchived}
        onSetConversationProject={handleSetConversationProject}
        onManageAgents={() => setIsAgentsOpen(true)}
        onManageSettings={() => setIsSettingsOpen(true)}
        onManagePlugins={() => setActiveView('plugins')}
        activeView={activeView}
        onManageKnowledgeBase={() => setActiveView('kb')}
        onShowChat={() => setActiveView('chat')}
        onShowGraph={() => setActiveView('graph')}
      />
      {activeView === 'kb' ? (
        <KnowledgeBasePage onBack={() => setActiveView('chat')} />
      ) : activeView === 'plugins' ? (
        <PluginsPage onBack={() => setActiveView('chat')} />
      ) : activeView === 'graph' ? (
        <GraphPage
          onBack={() => setActiveView('chat')}
          initialGraphOptions={
            (() => {
              const all = status?.agents || [];
              const enabled = all.filter((a) => a.enabled && a.graph_id);
              const selectedIds = currentConversation?.agent_ids;
              const selected =
                Array.isArray(selectedIds) && selectedIds.length > 0
                  ? enabled.filter((a) => selectedIds.includes(a.id))
                  : enabled;
              return selected.map((a) => ({ agent_name: a.name, graph_id: a.graph_id }));
            })()
          }
        />
      ) : (
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          onInterrupt={handleInterrupt}
          isLoading={isLoading}
          onExportConversation={() =>
            currentConversationId ? handleExportConversation(currentConversationId) : null
          }
          onSelectAgents={() => setIsConversationAgentsOpen(true)}
          onShowGraph={() => setActiveView('graph')}
          onRefreshConversation={async () => {
            if (!currentConversationId) return;
            try {
              const c = await api.getConversation(currentConversationId);
              setCurrentConversation(c);
            } catch (err) {
              console.warn('Failed to refresh conversation:', err);
            }
          }}
          allAgents={status?.agents || []}
          chairmanOptions={(() => (status?.agents || []).filter((a) => a?.enabled))()}
          defaultChairmanLabel={
            (() => {
              const spec = status?.chairman_model?.spec || '';
              const all = status?.agents || [];
              const agent = all.find((a) => a?.model_spec === spec);
              return agent?.name ? `${agent.name}` : spec;
            })()
          }
          graphOptions={
            (() => {
              const all = status?.agents || [];
              const enabled = all.filter((a) => a.enabled && a.graph_id);
              const selectedIds = currentConversation?.agent_ids;
              const selected =
                Array.isArray(selectedIds) && selectedIds.length > 0
                  ? enabled.filter((a) => selectedIds.includes(a.id))
                  : enabled;
              return selected.map((a) => ({ agent_name: a.name, graph_id: a.graph_id }));
            })()
          }
        />
      )}
      <AgentsModal
        open={isAgentsOpen}
        onClose={() => setIsAgentsOpen(false)}
        onChanged={loadStatus}
      />
      <SettingsModal open={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      {isConversationAgentsOpen && (
        <ConversationAgentsModal
          onClose={() => setIsConversationAgentsOpen(false)}
          conversationId={currentConversationId}
          initialAgentIds={currentConversation?.agent_ids}
          onSaved={() => {
            if (currentConversationId) {
              api.getConversation(currentConversationId).then(setCurrentConversation).catch(() => {});
            }
          }}
        />
      )}

    </div>
  );
}

export default App;
