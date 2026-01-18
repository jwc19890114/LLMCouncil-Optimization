/**
 * API client for the LLM Council backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

async function getErrorMessage(response, fallback) {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (typeof data?.message === 'string') return data.message;
    if (typeof data?.error === 'string') return data.error;
  } catch {
    return fallback;
  }
  return fallback;
}

export const api = {
  /**
   * Get backend status/config (no secrets).
   */
  async getStatus() {
    const response = await fetch(`${API_BASE}/api/status`, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error('Failed to get status');
    }
    return response.json();
  },

  async listAgents() {
    const response = await fetch(`${API_BASE}/api/agents`, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error('Failed to list agents');
    }
    return response.json();
  },

  async createAgent(agent) {
    const response = await fetch(`${API_BASE}/api/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agent),
    });
    if (!response.ok) {
      throw new Error('Failed to create agent');
    }
    return response.json();
  },

  async updateAgent(agentId, agent) {
    const response = await fetch(`${API_BASE}/api/agents/${agentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agent),
    });
    if (!response.ok) {
      throw new Error('Failed to update agent');
    }
    return response.json();
  },

  async deleteAgent(agentId) {
    const response = await fetch(`${API_BASE}/api/agents/${agentId}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error('Failed to delete agent');
    }
    return response.json();
  },

  async setAgentModels(models) {
    const response = await fetch(`${API_BASE}/api/agents/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(models),
    });
    if (!response.ok) {
      throw new Error('Failed to set agent models');
    }
    return response.json();
  },

  async generateAgentPersona({ name, model_spec = null }) {
    const response = await fetch(`${API_BASE}/api/agents/persona/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, model_spec }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '生成人设失败'));
    return response.json();
  },

  // Settings
  async getSettings() {
    const response = await fetch(`${API_BASE}/api/settings`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '加载设置失败'));
    return response.json();
  },

  async patchSettings(patch) {
    const response = await fetch(`${API_BASE}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch || {}),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '保存设置失败'));
    return response.json();
  },

  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      { cache: 'no-store' }
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  async setConversationKBDocIds(conversationId, docIds) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/kb/doc_ids`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: Array.isArray(docIds) ? docIds : [] }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '绑定文档失败'));
    return response.json();
  },

  async setConversationChairman(conversationId, { chairman_agent_id = '', chairman_model = '' } = {}) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/chairman`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chairman_agent_id, chairman_model }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '设置 Chairman 失败'));
    return response.json();
  },

  async setConversationAgents(conversationId, agentIds) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/agents`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agentIds),
    });
    if (!response.ok) {
      throw new Error('Failed to set conversation agents');
    }
    return response.json();
  },

  async deleteConversation(conversationId) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error('Failed to delete conversation');
    }
    return response.json();
  },

  async exportConversation(conversationId) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/export`);
    if (!response.ok) {
      throw new Error('Failed to export conversation');
    }
    return response.json();
  },

  async getConversationTrace(conversationId) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/trace`);
    if (!response.ok) {
      throw new Error('Failed to get conversation trace');
    }
    return response.json();
  },

  // Knowledge base
  async listKBDocuments() {
    const response = await fetch(`${API_BASE}/api/kb/documents`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '加载知识库文档失败'));
    return response.json();
  },

  async addKBDocument(doc) {
    const response = await fetch(`${API_BASE}/api/kb/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(doc),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '新增知识库文档失败'));
    return response.json();
  },

  async addKBDocumentsBatch({ documents, index_embeddings = null, embedding_model = null } = {}) {
    const response = await fetch(`${API_BASE}/api/kb/documents/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ documents, index_embeddings, embedding_model }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '批量新增知识库文档失败'));
    return response.json();
  },

  async updateKBDocument(docId, patch) {
    const response = await fetch(`${API_BASE}/api/kb/documents/${docId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '更新知识库文档失败'));
    return response.json();
  },

  async deleteKBDocument(docId) {
    const response = await fetch(`${API_BASE}/api/kb/documents/${docId}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '删除知识库文档失败'));
    return response.json();
  },

  async getKBDocument(docId) {
    const response = await fetch(`${API_BASE}/api/kb/documents/${docId}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '加载知识库文档失败'));
    return response.json();
  },

  // Knowledge graph
  async listKGGraphs(agentId = '') {
    const url = new URL(`${API_BASE}/api/kg/graphs`);
    if (agentId) url.searchParams.set('agent_id', agentId);
    const response = await fetch(url.toString(), { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '加载图谱列表失败'));
    return response.json();
  },

  async createKGGraph({ name, agent_id = '' }) {
    const response = await fetch(`${API_BASE}/api/kg/graphs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, agent_id }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '创建图谱失败'));
    return response.json();
  },

  async extractKG({ graph_id, text, model_spec = null, ontology = null }) {
    const response = await fetch(`${API_BASE}/api/kg/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ graph_id, text, model_spec, ontology }),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '抽取图谱失败'));
    return response.json();
  },

  async getKGGraph(graphId) {
    const response = await fetch(`${API_BASE}/api/kg/graphs/${graphId}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '加载图谱失败'));
    return response.json();
  },

  async queryKGSubgraph(graphId, q) {
    const url = new URL(`${API_BASE}/api/kg/graphs/${graphId}/subgraph`);
    url.searchParams.set('q', q || '');
    const response = await fetch(url.toString(), { cache: 'no-store' });
    if (!response.ok) throw new Error(await getErrorMessage(response, '子图搜索失败'));
    return response.json();
  },

  async interpretKG(graphId, payload) {
    const response = await fetch(`${API_BASE}/api/kg/graphs/${graphId}/interpret`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    if (!response.ok) throw new Error(await getErrorMessage(response, '生成解读失败'));
    return response.json();
  },

  async interpretKGStream(graphId, payload, onEvent) {
    const response = await fetch(`${API_BASE}/api/kg/graphs/${graphId}/interpret/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response, '生成解读失败'));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent?.(event.type, event);
          } catch {
            continue;
          }
        }
      }
    }
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
  },
};
