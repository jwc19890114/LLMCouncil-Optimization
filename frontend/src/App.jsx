import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import AgentsModal from './components/AgentsModal';
import ConversationAgentsModal from './components/ConversationAgentsModal';
import KnowledgeBasePage from './components/KnowledgeBasePage';
import GraphPage from './components/GraphPage';
import SettingsModal from './components/SettingsModal';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [isAgentsOpen, setIsAgentsOpen] = useState(false);
  const [isConversationAgentsOpen, setIsConversationAgentsOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [activeView, setActiveView] = useState('chat'); // chat | kb | graph

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
      downloadJson(`llm-council-${title}-${id}.json`, data);
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
        await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
          switch (eventType) {
            case 'stage0_start':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.loading.stage0 = true;
                return { ...prev, messages };
              });
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
                return { ...prev, messages };
              });
              break;

            case 'stage2b_complete':
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.stage2b = event.data;
                lastMsg.loading.stage2b = false;
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
            // Reload conversations to get updated title
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
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        status={status}
        currentConversationId={currentConversationId}
        currentConversation={currentConversation}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onDeleteConversation={handleDeleteConversation}
        onExportConversation={handleExportConversation}
        onManageAgents={() => setIsAgentsOpen(true)}
        onManageSettings={() => setIsSettingsOpen(true)}
        activeView={activeView}
        onManageKnowledgeBase={() => setActiveView('kb')}
        onShowChat={() => setActiveView('chat')}
        onShowGraph={() => setActiveView('graph')}
      />
      {activeView === 'kb' ? (
        <KnowledgeBasePage onBack={() => setActiveView('chat')} />
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
