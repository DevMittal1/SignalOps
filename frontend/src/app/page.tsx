'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  PhoneCall, 
  PhoneOff, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  Activity, 
  Briefcase, 
  Clock, 
  DollarSign, 
  User,
  Plus,
  LogOut,
  Lock,
  Edit2,
  Trash2,
  ChevronRight,
  Search,
  Sliders,
  ListTodo,
  TrendingUp,
  SlidersHorizontal
} from 'lucide-react';
import { LiveKitRoom, RoomAudioRenderer, useRoomContext } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';

// Constants
const LIVEKIT_URL = "wss://signalops-rjjzu2g7.livekit.cloud";
const BACKEND_API = process.env.NEXT_PUBLIC_BACKEND_API || "";

// --- Subcomponent: LiveKit event hook & data channel parser ---
function DataChannelListener({ 
  onTranscript, 
  onFact, 
  onSummary,
  onDisconnect,
  onLog
}: { 
  onTranscript: (role: string, text: string) => void;
  onFact: (fact: { type: string; value: string; confidence: number }) => void;
  onSummary: (summary: any) => void;
  onDisconnect: () => void;
  onLog: (logStr: string) => void;
}) {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handleDataReceived = (payload: Uint8Array, participant: any) => {
      const decoder = new TextDecoder();
      const str = decoder.decode(payload);
      try {
        const data = JSON.parse(str);
        onLog(`[Data Channel] Received event: ${data.type}`);
        
        if (data.type === "TRANSCRIPT") {
          onTranscript(data.role, data.text);
        } else if (data.type === "TOOL_EXECUTION") {
          onLog(`[AI Tool Executing] ${data.function}: ${JSON.stringify(data.arguments)}`);
          if (data.function === "append_call_fact") {
            onFact({
              type: data.arguments.fact_type,
              value: data.arguments.value,
              confidence: Number(data.arguments.confidence) || 1.0
            });
          } else if (data.function === "save_call_summary") {
            onSummary(data.arguments);
          }
        }
      } catch (e) {
        console.error("Failed to parse data channel message:", e);
      }
    };

    const handleDisconnected = () => {
      onDisconnect();
    };

    room.on(RoomEvent.DataReceived, handleDataReceived);
    room.on(RoomEvent.Disconnected, handleDisconnected);

    return () => {
      room.off(RoomEvent.DataReceived, handleDataReceived);
      room.off(RoomEvent.Disconnected, handleDisconnected);
    };
  }, [room, onTranscript, onFact, onSummary, onDisconnect, onLog]);

  return null;
}

// --- Main Page Component ---
export default function Page() {
  // Auth state
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string>("");
  const [authTab, setAuthTab] = useState<'login' | 'register'>('login');
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSuccess, setAuthSuccess] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  // CRM Workspace views state
  const [currentView, setCurrentView] = useState<'kanban' | 'grid' | 'logs' | 'audits'>('kanban');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Pipeline deals lists
  const [deals, setDeals] = useState<any[]>([]);
  const [selectedDealId, setSelectedDealId] = useState<string>("");
  const [selectedDeal, setSelectedDeal] = useState<any | null>(null);
  const [dealsLoading, setDealsLoading] = useState(false);

  // Grid pagination
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [totalDeals, setTotalDeals] = useState(0);

  // Modal forms
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', amount: '', stage: 'Discovery', close_date: '' });
  const [createError, setCreateError] = useState<string | null>(null);
  const [createLoading, setCreateLoading] = useState(false);

  const [showEditModal, setShowEditModal] = useState(false);
  const [editForm, setEditForm] = useState({ id: '', name: '', amount: '', stage: 'Discovery', close_date: '', confidence: 70 });
  const [editError, setEditError] = useState<string | null>(null);
  const [editLoading, setEditLoading] = useState(false);

  // Ticket creation
  const [newTicketText, setNewTicketText] = useState('');
  const [ticketLoading, setTicketLoading] = useState(false);

  // Call states
  const [ringing, setRinging] = useState(false);
  const [roomName, setRoomName] = useState("");
  const [lkToken, setLkToken] = useState<string | null>(null);
  const [callActive, setCallActive] = useState(false);
  const [backendConnected, setBackendConnected] = useState(false);
  const [callDuration, setCallDuration] = useState(0);

  // Live call log feeds & transcription drawer
  const [crmFacts, setCrmFacts] = useState<Array<{ time: string; msg: string }>>([]);
  const [transcripts, setTranscripts] = useState<Array<{ id: string; role: string; text: string }>>([]);
  const [telemetryLogs, setTelemetryLogs] = useState<string[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Check auth on mount
  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedUser = localStorage.getItem('username');
    if (savedToken && savedUser) {
      setAuthToken(savedToken);
      setUsername(savedUser);
    }
  }, []);

  // Duration timer for active calls
  useEffect(() => {
    if (callActive) {
      setCallDuration(0);
      timerRef.current = setInterval(() => {
        setCallDuration(prev => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
      setCallDuration(0);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [callActive]);

  // Fetch all deals for Kanban or computed KPIs (loads everything up to limit 100)
  const fetchAllDeals = useCallback(async () => {
    if (!authToken) return;
    try {
      const res = await fetch(`${BACKEND_API}/api/deals?limit=100&search=${encodeURIComponent(searchQuery)}`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        const nextDeals = data.data || [];
        setDeals(nextDeals);
        if (nextDeals.length > 0 && (!selectedDealId || !nextDeals.some((deal: { _id: string }) => deal._id === selectedDealId))) {
          setSelectedDealId(nextDeals[0]._id);
        } else if (nextDeals.length === 0 && selectedDealId) {
          setSelectedDealId("");
        }
      }
    } catch (err) {
      console.error("Failed to fetch all deals:", err);
    }
  }, [authToken, searchQuery, selectedDealId]);

  // Fetch paginated deals list specifically for grid view
  const fetchPaginatedDeals = useCallback(async () => {
    if (!authToken) return;
    setDealsLoading(true);
    try {
      const res = await fetch(
        `${BACKEND_API}/api/deals?page=${page}&limit=${limit}&search=${encodeURIComponent(searchQuery)}&sort_by=${sortField}&order=${sortOrder}`,
        {
          headers: { 'Authorization': `Bearer ${authToken}` }
        }
      );
      if (res.ok) {
        const data = await res.json();
        setTotalDeals(data.pagination?.total || 0);
        // If grid view, we align view list
        if (currentView === 'grid') {
          const nextDeals = data.data || [];
          setDeals(nextDeals);
          if (nextDeals.length > 0 && (!selectedDealId || !nextDeals.some((deal: { _id: string }) => deal._id === selectedDealId))) {
            setSelectedDealId(nextDeals[0]._id);
          } else if (nextDeals.length === 0 && selectedDealId) {
            setSelectedDealId("");
          }
        }
      }
    } catch (err) {
      console.error("Failed to fetch paginated deals:", err);
    } finally {
      setDealsLoading(false);
    }
  }, [authToken, page, limit, searchQuery, sortField, sortOrder, currentView, selectedDealId]);

  // Handle switching views and query loads
  useEffect(() => {
    if (authToken) {
      if (currentView === 'kanban' || currentView === 'audits') {
        fetchAllDeals();
      } else {
        fetchPaginatedDeals();
      }
    }
  }, [authToken, currentView, searchQuery, sortField, sortOrder, page, fetchAllDeals, fetchPaginatedDeals]);

  // Fetch detailed deal payload for workspace inspection
  const fetchSelectedDeal = useCallback(async () => {
    if (!authToken || !selectedDealId) return;
    try {
      const res = await fetch(`${BACKEND_API}/api/deals/${selectedDealId}`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedDeal(data);
      }
    } catch (err) {
      console.error("Failed to fetch deal details:", err);
    }
  }, [authToken, selectedDealId]);

  useEffect(() => {
    if (selectedDealId) {
      fetchSelectedDeal();
    } else {
      setSelectedDeal(null);
    }
  }, [selectedDealId, fetchSelectedDeal]);

  // Poll selected deal database updates if call is active
  useEffect(() => {
    if (!callActive || !selectedDealId) return;
    const interval = setInterval(() => {
      fetchSelectedDeal();
      // Keep pipeline metrics refreshed in background
      fetchAllDeals();
    }, 1500);
    return () => clearInterval(interval);
  }, [callActive, selectedDealId, fetchSelectedDeal, fetchAllDeals]);

  // Poll server for incoming ringing call status
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`${BACKEND_API}/api/status`);
        if (res.ok) {
          const data = await res.json();
          setBackendConnected(true);
          setRinging(data.ringing);
          if (data.ringing && data.room_name) {
            setRoomName(data.room_name);
            if (data.deal_id && data.deal_id !== selectedDealId) {
              setSelectedDealId(data.deal_id);
            }
          }
        } else {
          setBackendConnected(false);
        }
      } catch (e) {
        setBackendConnected(false);
      }
    };

    checkStatus();
    const interval = setInterval(checkStatus, 1500);
    return () => clearInterval(interval);
  }, [selectedDealId]);

  // Auth submits
  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setAuthSuccess(null);
    if (!authForm.username || !authForm.password) {
      setAuthError("Please fill in all fields.");
      return;
    }
    setAuthLoading(true);
    try {
      const endpoint = authTab === 'login' ? 'login' : 'register';
      const res = await fetch(`${BACKEND_API}/api/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm)
      });
      const data = await res.json();
      if (res.ok) {
        if (authTab === 'login') {
          localStorage.setItem('token', data.token);
          localStorage.setItem('username', data.username);
          setAuthToken(data.token);
          setUsername(data.username);
          setAuthForm({ username: '', password: '' });
        } else {
          localStorage.setItem('token', data.token);
          localStorage.setItem('username', data.username);
          setAuthToken(data.token);
          setUsername(data.username);
          setAuthForm({ username: '', password: '' });
        }
      } else {
        setAuthError(data.error || "Authentication failed");
      }
    } catch (err) {
      setAuthError("Failed to communicate with authentication server.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    setAuthToken(null);
    setUsername("");
    setDeals([]);
    setSelectedDealId("");
    setSelectedDeal(null);
  };

  // Create deal
  const handleCreateDealSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);
    if (!createForm.name || !createForm.close_date || !createForm.amount) {
      setCreateError("All fields are required.");
      return;
    }
    setCreateLoading(true);
    try {
      const res = await fetch(`${BACKEND_API}/api/deals`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          name: createForm.name,
          amount: parseFloat(createForm.amount),
          stage: createForm.stage,
          close_date: createForm.close_date
        })
      });
      const data = await res.json();
      if (res.ok) {
        setShowCreateModal(false);
        setCreateForm({ name: '', amount: '', stage: 'Discovery', close_date: '' });
        if (currentView === 'kanban' || currentView === 'audits') {
          fetchAllDeals();
        } else {
          fetchPaginatedDeals();
        }
        setSelectedDealId(data._id);
      } else {
        setCreateError(data.error || "Failed to create deal.");
      }
    } catch (err) {
      setCreateError("Network error. Could not create deal.");
    } finally {
      setCreateLoading(false);
    }
  };

  // Inline patch helper
  const patchDealFields = async (id: string, fields: any) => {
    try {
      const res = await fetch(`${BACKEND_API}/api/deals/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify(fields)
      });
      const data = await res.json();
      if (res.ok) {
        if (currentView === 'kanban' || currentView === 'audits') {
          fetchAllDeals();
        } else {
          fetchPaginatedDeals();
        }
        if (selectedDealId === id) {
          setSelectedDeal(data);
        }
        return data;
      }
      throw new Error(data.error || "Failed to update deal.");
    } catch (err) {
      console.error("Failed to patch deal fields:", err);
      throw err;
    }
  };

  // Drag simulation / Dropdown stage changes
  const handleStageChange = (id: string, newStage: string) => {
    patchDealFields(id, { stage: newStage }).catch(() => {
      if (currentView === 'kanban' || currentView === 'audits') {
        fetchAllDeals();
      } else {
        fetchPaginatedDeals();
      }
    });
  };

  // Range Slider Updates
  const handleAmountSliderChange = (amount: number) => {
    if (!selectedDealId) return;
    setSelectedDeal((prev: any) => prev ? { ...prev, amount } : null);
    patchDealFields(selectedDealId, { amount }).catch(fetchSelectedDeal);
  };

  const handleConfidenceSliderChange = (confidence: number) => {
    if (!selectedDealId) return;
    setSelectedDeal((prev: any) => prev ? { ...prev, confidence } : null);
    patchDealFields(selectedDealId, { confidence }).catch(fetchSelectedDeal);
  };

  // Delete opportunity
  const handleDeleteDeal = async (id: string) => {
    if (!confirm("Are you sure you want to delete this deal? All logs, checklists, and summaries will be lost.")) {
      return;
    }
    try {
      const res = await fetch(`${BACKEND_API}/api/deals/${id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${authToken}`
        }
      });
      if (res.ok) {
        setSelectedDealId("");
        setSelectedDeal(null);
        if (currentView === 'kanban' || currentView === 'audits') {
          fetchAllDeals();
        } else {
          fetchPaginatedDeals();
        }
      }
    } catch (err) {
      console.error("Failed to delete deal:", err);
    }
  };

  // Ticket CRUD resolution
  const handleResolveTicket = async (dealId: string, ticketId: string, currentStatus: string) => {
    const nextStatus = currentStatus === 'open' ? 'resolved' : 'open';
    try {
      const res = await fetch(`${BACKEND_API}/api/deals/${dealId}/tickets/${ticketId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({ status: nextStatus })
      });
      if (res.ok) {
        fetchSelectedDeal();
      }
    } catch (err) {
      console.error("Failed to update ticket status:", err);
    }
  };

  // Add manual ticket
  const handleAddManualTicket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTicketText.trim() || !selectedDealId) return;
    setTicketLoading(true);
    try {
      const res = await fetch(`${BACKEND_API}/api/deals/${selectedDealId}/tickets`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          text: newTicketText,
          source: 'Manual Rep Entry'
        })
      });
      if (res.ok) {
        setNewTicketText('');
        fetchSelectedDeal();
      }
    } catch (err) {
      console.error("Failed to add manual ticket:", err);
    } finally {
      setTicketLoading(false);
    }
  };

  // Trigger outbound call simulation
  const handleTriggerTestCall = async () => {
    if (!selectedDealId) {
      alert("Please select or create a deal first.");
      return;
    }
    try {
      const randomRoom = `room_${Math.floor(Date.now() / 1000)}`;
      await fetch(`${BACKEND_API}/api/trigger`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({ 
          room_name: randomRoom,
          deal_id: selectedDealId,
          rep_id: "rep_204"
        })
      });
      setRoomName(randomRoom);
      setRinging(true);
    } catch (e) {
      console.error("Failed to trigger call:", e);
    }
  };

  // Accept incoming call
  const handleAcceptCall = async () => {
    if (!roomName) return;
    try {
      try {
        await fetch(`${BACKEND_API}/api/clear`, { method: 'POST' });
      } catch (err) {
        console.error("Failed to clear ringing state:", err);
      }

      const res = await fetch(`${BACKEND_API}/api/token?room=${roomName}&identity=Aarav&deal_id=${selectedDealId}`);
      if (res.ok) {
        const data = await res.json();
        setLkToken(data.token);
        setCallActive(true);
        setRinging(false);
        
        setTranscripts([]);
        setTelemetryLogs([]);
        setCrmFacts([]);
        addCrmLog("System", `Live interview session established for room: ${roomName}`);
        addTelemetryLog(`Voice channel opened. Connecting to WebRTC server...`);
      }
    } catch (e) {
      console.error("Error connecting to call:", e);
    }
  };

  // Hangup call
  const handleDeclineOrDisconnect = async () => {
    setCallActive(false);
    setLkToken(null);
    setRinging(false);
    try {
      await fetch(`${BACKEND_API}/api/clear`, { method: 'POST' });
    } catch (e) {
      console.error("Failed to clear trigger status:", e);
    }
    addCrmLog("System", "Call session terminated.");
    if (currentView === 'kanban' || currentView === 'audits') {
      fetchAllDeals();
    } else {
      fetchPaginatedDeals();
    }
    fetchSelectedDeal();
  };

  const addCrmLog = (source: string, msg: string) => {
    const timeStr = new Date().toLocaleTimeString();
    setCrmFacts(prev => [{ time: timeStr, msg: `[${source}] ${msg}` }, ...prev]);
  };

  const addTelemetryLog = (logStr: string) => {
    setTelemetryLogs(prev => [`[${new Date().toLocaleTimeString()}] ${logStr}`, ...prev]);
  };

  // Callback: Handle transcript streaming from agent
  const handleTranscriptReceived = useCallback((role: string, text: string) => {
    setTranscripts(prev => {
      if (prev.length > 0 && prev[prev.length - 1].role === role) {
        const copy = [...prev];
        copy[copy.length - 1] = {
          ...copy[copy.length - 1],
          text: text
        };
        return copy;
      }
      return [...prev, { id: Math.random().toString(), role, text }];
    });
  }, []);

  // Callback: Handle facts dynamically captured by AI tools
  const handleFactReceived = useCallback((fact: { type: string; value: string; confidence: number }) => {
    addCrmLog("AI Agent (append_call_fact)", `Fact recorded: ${fact.type}="${fact.value}" (confidence=${fact.confidence.toFixed(1)})`);
  }, []);

  // Callback: Handle final call summary saved by AI at the end
  const handleSummaryReceived = useCallback((summaryData: any) => {
    addCrmLog("AI Agent (save_call_summary)", `Summary Saved: "${summaryData.primary_blocker}"`);
    fetchSelectedDeal(); // pull final updates immediately
  }, [fetchSelectedDeal]);

  // Check sentiment indicators on transcript
  const getTranscriptSentimentBadge = (text: string) => {
    const lower = text.toLowerCase();
    if (lower.includes("objection") || lower.includes("risk") || lower.includes("blocked") || lower.includes("waiting") || lower.includes("delay")) {
      return <span className="badge badge-rose" style={{ fontSize: '0.65rem', marginLeft: '0.5rem' }}>Objection Flagged</span>;
    }
    if (lower.includes("signed") || lower.includes("buying") || lower.includes("agreed") || lower.includes("approved") || lower.includes("closing")) {
      return <span className="badge badge-success" style={{ fontSize: '0.65rem', marginLeft: '0.5rem' }}>Buying Signal</span>;
    }
    return null;
  };

  // Dynamic calculations for CRM analytics panel
  const getPipelineValue = () => {
    return deals.reduce((acc, d) => acc + (d.amount || 0), 0);
  };

  const getRiskPct = () => {
    if (!selectedDeal) return 0;
    const delayedCount = selectedDeal.checklist?.filter((item: any) => item.status === 'delayed').length || 0;
    const totalCount = selectedDeal.checklist?.length || 0;
    return totalCount > 0 ? Math.round((delayedCount / totalCount) * 100) : 0;
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0
    }).format(amount);
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Render auth screen
  if (!authToken) {
    return (
      <div className="auth-wrapper">
        <div className="auth-card">
          <div className="auth-header-section">
            <h1 className="auth-title">SignalOps</h1>
            <p className="auth-subtitle">Revenue Intelligence Operations Console</p>
          </div>

          <div className="auth-tabs">
            <button 
              className={`auth-tab ${authTab === 'login' ? 'auth-tab-active' : ''}`}
              onClick={() => { setAuthTab('login'); setAuthError(null); }}
            >
              Log In
            </button>
            <button 
              className={`auth-tab ${authTab === 'register' ? 'auth-tab-active' : ''}`}
              onClick={() => { setAuthTab('register'); setAuthError(null); }}
            >
              Register
            </button>
          </div>

          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="username">Username</label>
              <div className="form-input-wrapper">
                <User size={16} className="form-input-icon" />
                <input 
                  type="text" 
                  id="username" 
                  className="form-input" 
                  placeholder="Enter username" 
                  value={authForm.username}
                  onChange={(e) => setAuthForm(prev => ({ ...prev, username: e.target.value }))}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="password">Password</label>
              <div className="form-input-wrapper">
                <Lock size={16} className="form-input-icon" />
                <input 
                  type="password" 
                  id="password" 
                  className="form-input" 
                  placeholder="Enter password" 
                  value={authForm.password}
                  onChange={(e) => setAuthForm(prev => ({ ...prev, password: e.target.value }))}
                />
              </div>
            </div>

            {authError && <div className="auth-alert auth-alert-error">{authError}</div>}
            {authSuccess && <div className="auth-alert auth-alert-success">{authSuccess}</div>}

            <button type="submit" className="form-submit-btn" disabled={authLoading}>
              {authLoading ? "Authenticating..." : authTab === 'login' ? "Access Console" : "Create Account"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // Render main crm dashboard
  return (
    <div className="dashboard-container">
      {/* Header */}
      <div className="header">
        <div className="logo-section">
          <h1><span className="logo-dot"></span> SignalOps CRM</h1>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '8px', 
              height: '8px', 
              borderRadius: '50%', 
              backgroundColor: backendConnected ? 'var(--accent-emerald)' : 'var(--accent-rose)' 
            }}></span>
            <span style={{ color: 'var(--text-secondary)' }}>
              {backendConnected ? "Live telemetry online" : "Connecting server..."}
            </span>
          </div>

          <div className="user-menu">
            <User size={14} style={{ color: 'var(--accent-cyan)' }} />
            <span style={{ fontWeight: 600 }}>{username}</span>
            <span style={{ color: 'var(--text-muted)' }}>|</span>
            <button className="logout-btn" onClick={handleLogout} title="Sign Out">
              <LogOut size={14} />
            </button>
          </div>

          <button 
            className="trigger-btn" 
            onClick={handleTriggerTestCall}
            disabled={!selectedDealId}
            style={{ opacity: selectedDealId ? 1 : 0.6 }}
          >
            <PhoneCall size={16} /> Audit Current Deal
          </button>
        </div>
      </div>

      {/* KPI Cards section */}
      <div className="kpi-grid">
        <div className="kpi-card kpi-card-cyan">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              <span className="kpi-label">Active Pipeline</span>
              <span className="kpi-val">{formatCurrency(getPipelineValue())}</span>
            </div>
            <div style={{ background: 'rgba(6, 182, 212, 0.08)', color: 'var(--accent-cyan)', padding: '0.6rem', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <DollarSign size={18} />
            </div>
          </div>
        </div>
        <div className="kpi-card kpi-card-emerald">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              <span className="kpi-label">Estimated Win Rate</span>
              <span className="kpi-val">72%</span>
            </div>
            <div style={{ background: 'rgba(13, 148, 136, 0.08)', color: 'var(--accent-emerald)', padding: '0.6rem', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <TrendingUp size={18} />
            </div>
          </div>
        </div>
        <div className="kpi-card kpi-card-rose">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              <span className="kpi-label">Active Audits</span>
              <span className="kpi-val">{callActive ? 1 : 0}</span>
            </div>
            <div style={{ background: 'rgba(244, 63, 94, 0.08)', color: 'var(--accent-rose)', padding: '0.6rem', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Activity size={18} className={callActive ? "waveform-bar-animated" : ""} />
            </div>
          </div>
        </div>
        <div className="kpi-card kpi-card-orange">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
              <span className="kpi-label">Selected Deal Risk</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ fontSize: '0.8rem', fontWeight: 'bold', color: getRiskPct() > 30 ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                  {getRiskPct()}%
                </span>
                <AlertCircle size={14} style={{ color: getRiskPct() > 30 ? 'var(--accent-rose)' : 'var(--accent-orange)' }} />
              </div>
            </div>
            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.04)', borderRadius: '4px', marginTop: '0.4rem' }}>
              <div style={{ 
                width: `${getRiskPct()}%`, 
                height: '100%', 
                background: getRiskPct() > 40 ? 'var(--accent-rose)' : 'var(--accent-orange)', 
                borderRadius: '4px',
                transition: 'width 0.3s ease'
              }}></div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Workspace toggle views & filters */}
      <div className="view-bar">
        <div className="view-tabs">
          <button 
            className={`view-tab ${currentView === 'kanban' ? 'view-tab-active' : ''}`}
            onClick={() => setCurrentView('kanban')}
          >
            Kanban Board
          </button>
          <button 
            className={`view-tab ${currentView === 'grid' ? 'view-tab-active' : ''}`}
            onClick={() => setCurrentView('grid')}
          >
            Pipeline Grid
          </button>
          <button 
            className={`view-tab ${currentView === 'logs' ? 'view-tab-active' : ''}`}
            onClick={() => setCurrentView('logs')}
          >
            Audited Activities
          </button>
          <button 
            className={`view-tab ${currentView === 'audits' ? 'view-tab-active' : ''}`}
            onClick={() => setCurrentView('audits')}
          >
            Voice AI Audits
          </button>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', flexShrink: 0, justifyContent: 'flex-end', alignItems: 'center' }}>
          <div className="search-input-wrapper">
            <Search size={14} className="form-input-icon" />
            <input 
              type="text" 
              className="search-input" 
              placeholder="Search opportunity name..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <button className="trigger-btn" onClick={() => setShowCreateModal(true)} style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            <Plus size={14} /> Add Deal
          </button>
        </div>
      </div>

      {/* WORKSPACE AREA */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1.1fr)', gap: '2rem', marginTop: '1.5rem' }}>
        
        {/* LEFT COMPONENT: Selected View */}
        <div style={{ minWidth: 0 }}>
          {dealsLoading && (
            <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '4rem' }}>
              Refreshing pipeline records...
            </div>
          )}

          {!dealsLoading && currentView === 'kanban' && (
            <div className="kanban-board">
              {['Discovery', 'Proposal', 'Security Review', 'Closed-Won'].map(columnStage => {
                const columnDeals = deals.filter(d => d.stage === columnStage);
                return (
                  <div key={columnStage} className="kanban-column">
                    <div className="kanban-column-header">
                      <span className="kanban-column-title">{columnStage}</span>
                      <span className="kanban-column-badge">{columnDeals.length}</span>
                    </div>

                    <div className="kanban-cards-wrapper">
                      {columnDeals.map(deal => (
                        <div 
                          key={deal._id} 
                          className={`kanban-card ${selectedDealId === deal._id ? 'kanban-card-selected' : ''}`}
                          onClick={() => setSelectedDealId(deal._id)}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <span className="kanban-card-title">{deal.name}</span>
                            <span className="kanban-card-val">{formatCurrency(deal.amount)}</span>
                          </div>

                          <div className="kanban-card-footer">
                            <span style={{ fontSize: '0.75rem', color: 'var(--accent-orange)' }}>
                              Confidence: {deal.confidence || 70}%
                            </span>
                            <div className="kanban-card-actions" onClick={e => e.stopPropagation()}>
                              <select 
                                value={deal.stage} 
                                onChange={(e) => handleStageChange(deal._id, e.target.value)}
                                style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-primary)', fontSize: '0.75rem', borderRadius: '4px', padding: '2px' }}
                              >
                                <option value="Discovery">Discovery</option>
                                <option value="Proposal">Proposal</option>
                                <option value="Security Review">Security Review</option>
                                <option value="Closed-Won">Closed-Won</option>
                              </select>
                              <button 
                                className="kanban-card-btn kanban-card-btn-delete"
                                onClick={() => handleDeleteDeal(deal._id)}
                                title="Delete Opportunity"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                      {columnDeals.length === 0 && (
                        <div className="kanban-empty-card">
                          No opportunities in this stage.
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {!dealsLoading && currentView === 'grid' && (
            <div>
              <div className="grid-table-container">
                <table className="grid-table">
                  <thead>
                    <tr>
                      <th onClick={() => { setSortField('name'); setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc'); }}>Name</th>
                      <th onClick={() => { setSortField('amount'); setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc'); }}>Value</th>
                      <th onClick={() => { setSortField('stage'); setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc'); }}>Stage</th>
                      <th onClick={() => { setSortField('confidence'); setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc'); }}>Confidence</th>
                      <th onClick={() => { setSortField('close_date'); setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc'); }}>Target Close</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map(deal => (
                      <tr 
                        key={deal._id} 
                        className={selectedDealId === deal._id ? 'grid-table-row-selected' : ''}
                        onClick={() => setSelectedDealId(deal._id)}
                      >
                        <td style={{ fontWeight: 600 }}>{deal.name}</td>
                        <td style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{formatCurrency(deal.amount)}</td>
                        <td>
                          <span className={`badge ${
                            deal.stage === 'Discovery' ? 'badge-info' :
                            deal.stage === 'Proposal' ? 'badge-warning' :
                            deal.stage === 'Security Review' ? 'badge-success' : 'badge-rose'
                          }`}>
                            {deal.stage}
                          </span>
                        </td>
                        <td>{deal.confidence || 70}%</td>
                        <td>{deal.close_date}</td>
                        <td onClick={e => e.stopPropagation()}>
                          <div style={{ display: 'flex', gap: '0.4rem' }}>
                            <button 
                              className="kanban-card-btn"
                              onClick={() => {
                                setEditForm({
                                  id: deal._id,
                                  name: deal.name,
                                  amount: deal.amount.toString(),
                                  stage: deal.stage,
                                  close_date: deal.close_date,
                                  confidence: deal.confidence || 70
                                });
                                setShowEditModal(true);
                              }}
                            >
                              <Edit2 size={12} />
                            </button>
                            <button 
                              className="kanban-card-btn kanban-card-btn-delete"
                              onClick={() => handleDeleteDeal(deal._id)}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {deals.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <div className="grid-empty-state">No opportunities match the current filters.</div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Grid Pagination Footer */}
              <div className="pagination-container">
                <button 
                  className="pagination-btn" 
                  disabled={page <= 1}
                  onClick={() => setPage(prev => Math.max(prev - 1, 1))}
                >
                  &lt;&lt; Previous
                </button>
                <span className="pagination-info">
                  Page <strong>{page}</strong> of {Math.ceil(totalDeals / limit) || 1} (Total: {totalDeals} opportunities)
                </span>
                <button 
                  className="pagination-btn"
                  disabled={page >= Math.ceil(totalDeals / limit)}
                  onClick={() => setPage(prev => prev + 1)}
                >
                  Next &gt;&gt;
                </button>
              </div>
            </div>
          )}

          {!dealsLoading && currentView === 'logs' && selectedDeal && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">Audit Log Timeline: {selectedDeal.name}</div>
              </div>
              <div className="timeline-feed">
                {(!selectedDeal.events || selectedDeal.events.length === 0) ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', padding: '1rem' }}>
                    No audit records logged yet.
                  </div>
                ) : (
                  selectedDeal.events.map((evt: any, idx: number) => (
                    <div className="timeline-item" key={idx}>
                      <div className={`timeline-icon ${
                        evt.type === 'stage_changed' ? 'timeline-icon-stage' :
                        evt.type === 'amount_changed' ? 'timeline-icon-amount' :
                        evt.type === 'confidence_changed' ? 'timeline-icon-confidence' :
                        evt.type === 'ticket_created' ? 'timeline-icon-ticket' : 'timeline-icon-created'
                      }`}></div>
                      <div className="timeline-details">
                        <span className="timeline-time">
                          {new Date(evt.timestamp * 1000).toLocaleString()}
                        </span>
                        <span className="timeline-desc">{evt.description}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {!dealsLoading && currentView === 'logs' && !selectedDeal && (
            <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '300px' }}>
              <div style={{ color: 'var(--text-muted)' }}>
                Select an opportunity to inspect its audited activities list.
              </div>
            </div>
          )}

          {!dealsLoading && currentView === 'audits' && (
            <div className="audits-dashboard">
              <div style={{ marginBottom: '2rem' }}>
                <h3 style={{ color: 'var(--text-primary)', marginBottom: '1rem', fontSize: '1.25rem' }}>Pending Voice Audits</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {deals.filter(d => !d.calls || d.calls.length === 0 || (Date.now() - (d.calls[d.calls.length - 1].timestamp * 1000) > 14 * 24 * 60 * 60 * 1000)).map((deal, idx) => (
                    <div key={idx} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1.25rem' }}>
                      <div>
                        <div style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '0.25rem' }}>{deal.name}</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                          Stage: {deal.stage} • Amount: ${deal.amount?.toLocaleString()} • 
                          {!deal.calls || deal.calls.length === 0 ? " Never Audited" : ` Last Audited: ${new Date(deal.calls[deal.calls.length - 1].timestamp * 1000).toLocaleDateString()}`}
                        </div>
                      </div>
                      <button className="primary-btn" onClick={() => { setSelectedDealId(deal._id); setTimeout(() => handleTriggerTestCall(), 100); }} style={{ padding: '0.5rem 1.5rem' }}>
                        Start Voice Audit
                      </button>
                    </div>
                  ))}
                  {deals.filter(d => !d.calls || d.calls.length === 0 || (Date.now() - (d.calls[d.calls.length - 1].timestamp * 1000) > 14 * 24 * 60 * 60 * 1000)).length === 0 && (
                    <div style={{ color: 'var(--text-muted)', padding: '1rem', backgroundColor: 'var(--bg-card)', borderRadius: '0.5rem', textAlign: 'center' }}>
                      No pending audits! All pipelines are up to date.
                    </div>
                  )}
                </div>
              </div>

              <div>
                <h3 style={{ color: 'var(--text-primary)', marginBottom: '1rem', fontSize: '1.25rem' }}>Completed Audits</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {deals.filter(d => d.calls && d.calls.length > 0 && (Date.now() - (d.calls[d.calls.length - 1].timestamp * 1000) <= 14 * 24 * 60 * 60 * 1000)).map((deal, idx) => (
                    <div key={idx} className="card" style={{ padding: '1.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                        <div>
                          <div style={{ color: 'var(--text-primary)', fontWeight: '600', marginBottom: '0.25rem' }}>{deal.name}</div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                            Last Audited: {new Date(deal.calls[deal.calls.length - 1].timestamp * 1000).toLocaleString()} • Duration: {Math.round(deal.calls[deal.calls.length - 1].duration_seconds)}s
                          </div>
                        </div>
                        <button className="secondary-btn" onClick={() => { setSelectedDealId(deal._id); setTimeout(() => handleTriggerTestCall(), 100); }} style={{ fontSize: '0.85rem', padding: '0.4rem 1rem' }}>
                          Re-audit
                        </button>
                      </div>
                      
                      <div className="audit-history-panel" style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border-color)' }}>
                        {deal.calls[deal.calls.length - 1].evaluation?.summary && (
                          <div style={{ marginBottom: '1rem' }}>
                            <strong style={{ display: 'block', color: 'var(--text-primary)', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Audit Summary</strong>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: '1.4' }}>{deal.calls[deal.calls.length - 1].evaluation.summary}</p>
                          </div>
                        )}
                        
                        {(deal.calls[deal.calls.length - 1].actions_taken && deal.calls[deal.calls.length - 1].actions_taken.length > 0) && (
                          <div style={{ marginBottom: '1rem' }}>
                            <strong style={{ display: 'block', color: 'var(--text-primary)', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Actions Taken</strong>
                            <ul style={{ margin: 0, paddingLeft: '1.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                              {deal.calls[deal.calls.length - 1].actions_taken.map((action: any, aIdx: number) => (
                                <li key={aIdx}>{action.description}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {(deal.calls[deal.calls.length - 1].tools_called && deal.calls[deal.calls.length - 1].tools_called.length > 0) && (
                          <div style={{ marginBottom: '1rem' }}>
                            <strong style={{ display: 'block', color: 'var(--text-primary)', marginBottom: '0.25rem', fontSize: '0.85rem' }}>Tools Triggered</strong>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                              {deal.calls[deal.calls.length - 1].tools_called.map((tool: any, tIdx: number) => (
                                <span key={tIdx} className="badge badge-warning" style={{ fontSize: '0.75rem' }}>{tool.function}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {deals.filter(d => d.calls && d.calls.length > 0 && (Date.now() - (d.calls[d.calls.length - 1].timestamp * 1000) <= 14 * 24 * 60 * 60 * 1000)).length === 0 && (
                    <div style={{ color: 'var(--text-muted)', padding: '1rem', backgroundColor: 'var(--bg-card)', borderRadius: '0.5rem', textAlign: 'center' }}>
                      No recently completed audits.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COMPONENT: Opportunity Detailed Worksheet */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {selectedDeal ? (
            <div className="card">
              <div className="card-header" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.5rem' }}>
                <span className="badge badge-info">{selectedDeal.stage} Stage</span>
                <h3 style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>{selectedDeal.name}</h3>
              </div>

              {/* Slider Worksheets */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginTop: '0.5rem' }}>
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Opportunity Amount Value</span>
                    <strong>{formatCurrency(selectedDeal.amount)}</strong>
                  </div>
                  <input 
                    type="range" 
                    min="10000" 
                    max="500000" 
                    step="5000"
                    value={selectedDeal.amount}
                    onChange={(e) => handleAmountSliderChange(Number(e.target.value))}
                    className="slider-input"
                  />
                </div>

                <div className="slider-container">
                  <div className="slider-header">
                    <span>AE Closing Confidence</span>
                    <strong>{selectedDeal.confidence || 70}%</strong>
                  </div>
                  <input 
                    type="range" 
                    min="10" 
                    max="100" 
                    step="5"
                    value={selectedDeal.confidence || 70}
                    onChange={(e) => handleConfidenceSliderChange(Number(e.target.value))}
                    className="slider-input"
                  />
                </div>

                <div className="deal-intel-panel">
                  <div className="deal-intel-header">
                    <span>Most Needed Now</span>
                    <strong>{selectedDeal.priority || 'medium'} priority</strong>
                  </div>
                  <div className="deal-intel-grid">
                    <div className="deal-intel-block">
                      <span className="deal-intel-label">Risk Flags</span>
                      <ul className="deal-intel-list">
                        {(selectedDeal.risk_flags || ['No risks recorded yet.']).slice(0, 3).map((risk: string, idx: number) => (
                          <li key={idx}>{risk}</li>
                        ))}
                      </ul>
                    </div>
                    <div className="deal-intel-block">
                      <span className="deal-intel-label">Action Points</span>
                      <ul className="deal-intel-list">
                        {(selectedDeal.next_best_actions || ['Run an AI audit to capture the next action.']).slice(0, 3).map((action: string, idx: number) => (
                          <li key={idx}>{action}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <div className="deal-intel-footer">
                    <span>Health score: <strong>{selectedDeal.health_score ?? 'N/A'}</strong></span>
                    <span>Last update: <strong>{selectedDeal.last_rep_update_days_ago ?? 'N/A'}d ago</strong></span>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '1rem' }}>
                  <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>Checklist Status</h4>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    {selectedDeal.checklist?.map((item: any) => (
                      <div className="checklist-item" key={item.id}>
                        <div className={`checklist-box ${
                          item.status === 'checked' ? 'checklist-box-checked' : 
                          item.status === 'delayed' ? 'checklist-box-delayed' : ''
                        }`}>
                          {item.status === 'checked' && <span style={{ fontSize: '0.75rem' }}>✓</span>}
                          {item.status === 'delayed' && <span style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>!</span>}
                        </div>
                        <span className={`checklist-text ${
                          item.status === 'checked' ? 'checklist-text-checked' : 
                          item.status === 'delayed' ? 'checklist-text-delayed' : ''
                        }`}>
                          {item.text}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Objection Tickets Subworkspace */}
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '1rem' }}>
                  <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>Objections & Tickets</h4>
                  
                  <div className="tickets-section">
                    {(!selectedDeal.tickets || selectedDeal.tickets.length === 0) ? (
                      <div className="ticket-empty-state">No objections raised for this opportunity.</div>
                    ) : (
                      selectedDeal.tickets.map((tkt: any) => (
                        <div 
                          key={tkt.id} 
                          className={`ticket-item ${tkt.status === 'resolved' ? 'ticket-item-resolved' : ''}`}
                        >
                          <div className="ticket-item-meta">
                            <span className="ticket-item-text">{tkt.text}</span>
                            <span className="ticket-item-source">{tkt.source}</span>
                          </div>
                          <button 
                            className={tkt.status === 'resolved' ? 'ticket-reopen-btn' : 'ticket-resolve-btn'}
                            onClick={() => handleResolveTicket(selectedDeal._id, tkt.id, tkt.status)}
                          >
                            {tkt.status === 'resolved' ? 'Reopen' : 'Resolve'}
                          </button>
                        </div>
                      ))
                    )}

                    <form className="ticket-add-form" onSubmit={handleAddManualTicket}>
                      <input 
                        type="text" 
                        className="ticket-add-input" 
                        placeholder="Log manual objection..."
                        value={newTicketText}
                        onChange={e => setNewTicketText(e.target.value)}
                        disabled={ticketLoading}
                      />
                      <button type="submit" className="ticket-add-btn" disabled={ticketLoading}>
                        Add
                      </button>
                    </form>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '300px' }}>
              <div style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                <Briefcase size={36} style={{ marginBottom: '1rem', opacity: 0.4 }} />
                <p>Select an opportunity card to examine revenue worksheet</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ACTIVE CALL VOICE TELEMETRY DRAWER */}
      {callActive && lkToken && (
        <div className="telemetry-drawer-overlay">
          <div className="telemetry-drawer">
            <div className="telemetry-drawer-header">
              <span className="telemetry-drawer-title">Voice AI Telemetry</span>
              <button className="dialog-close-btn" onClick={handleDeclineOrDisconnect}>
                <XCircle size={20} />
              </button>
            </div>

            <div className="telemetry-drawer-body">
              {/* Call Details */}
              <div style={{ background: 'rgba(255,255,255,0.02)', padding: '1rem', borderRadius: '12px', border: '1px solid var(--border-light)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Status:</span>
                  <span style={{ color: 'var(--accent-rose)', fontWeight: 'bold' }}>LIVE AUDIT IN PROGRESS</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Session Duration:</span>
                  <span style={{ fontFamily: 'monospace', color: 'var(--text-primary)' }}>{formatDuration(callDuration)}</span>
                </div>
              </div>

              {/* Waveform */}
              <div>
                <span className="kpi-label" style={{ marginBottom: '0.5rem', display: 'block' }}>Audio Volume Waves</span>
                <div className="waveform-section" style={{ background: 'rgba(0,0,0,0.2)' }}>
                  <div className="sound-wave-visualizer" style={{ margin: '0 auto' }}>
                    <div className="sound-wave-bar waveform-bar-animated"></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.1s' }}></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.3s' }}></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.2s' }}></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.4s' }}></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.15s' }}></div>
                    <div className="sound-wave-bar waveform-bar-animated" style={{ animationDelay: '0.35s' }}></div>
                  </div>
                </div>
              </div>

              {/* Transcripts with sentiment flags */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <span className="kpi-label" style={{ marginBottom: '0.5rem', display: 'block' }}>Live Speech Transcript</span>
                <div className="transcription-feed" style={{ flex: 1, maxHeight: '240px', background: 'rgba(0,0,0,0.2)' }}>
                  {transcripts.map(t => (
                    <div key={t.id} className={`speech-bubble ${t.role === 'user' ? 'bubble-user' : 'bubble-agent'}`} style={{ padding: '0.65rem 0.85rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span className={`bubble-sender ${t.role === 'user' ? 'bubble-sender-user' : 'bubble-sender-agent'}`}>
                          {t.role === 'user' ? 'Aarav (AE)' : 'AI Revenue Operations'}
                        </span>
                        {getTranscriptSentimentBadge(t.text)}
                      </div>
                      <div style={{ fontSize: '0.9rem', marginTop: '0.2rem' }}>{t.text}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Live telemetry raw log */}
              <div>
                <span className="kpi-label" style={{ marginBottom: '0.5rem', display: 'block' }}>Tool Executions & Database Writes</span>
                <div className="console-log-box">
                  {telemetryLogs.length === 0 ? (
                    <div style={{ color: 'var(--text-muted)' }}>Waiting for WebRTC data channel events...</div>
                  ) : (
                    telemetryLogs.map((log, index) => (
                      <div key={index}>{log}</div>
                    ))
                  )}
                </div>
              </div>

              {/* Disconnect Button */}
              <button 
                className="call-btn-disconnect" 
                style={{ width: '100%', padding: '0.85rem' }} 
                onClick={handleDeclineOrDisconnect}
              >
                Terminate Session
              </button>
            </div>

            {/* LiveKit component hookup */}
            <LiveKitRoom
              video={false}
              audio={true}
              token={lkToken}
              serverUrl={LIVEKIT_URL}
              connect={true}
              data-lk-theme="default"
            >
              <RoomAudioRenderer />
              <DataChannelListener
                onTranscript={handleTranscriptReceived}
                onFact={handleFactReceived}
                onSummary={handleSummaryReceived}
                onDisconnect={handleDeclineOrDisconnect}
                onLog={addTelemetryLog}
              />
            </LiveKitRoom>
          </div>
        </div>
      )}

      {/* Ringing Modal */}
      {ringing && (
        <div className="ringing-modal-overlay">
          <div className="ringing-card">
            <div className="ringing-phone-icon">
              <PhoneCall size={36} />
            </div>
            <div className="caller-info">
              <h2>Revenue Call Audit</h2>
              <p>Acme Revenue AI Operations Assistant</p>
            </div>
            <div className="ringing-actions">
              <button className="ringing-btn btn-accept" onClick={handleAcceptCall}>
                Answer
              </button>
              <button className="ringing-btn btn-decline" onClick={handleDeclineOrDisconnect}>
                Decline
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Deal Modal */}
      {showCreateModal && (
        <div className="dialog-overlay">
          <div className="dialog-content">
            <div className="dialog-header">
              <h2 className="dialog-title">Create New Deal</h2>
              <button className="dialog-close-btn" onClick={() => setShowCreateModal(false)}>
                <XCircle size={20} />
              </button>
            </div>

            <form className="dialog-form" onSubmit={handleCreateDealSubmit}>
              <div className="form-group">
                <label className="form-label" htmlFor="dealName">Deal Name</label>
                <input 
                  type="text" 
                  id="dealName" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }} 
                  placeholder="e.g. Acme Renewal Expansion"
                  value={createForm.name}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, name: e.target.value }))}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="dealAmount">Value (USD)</label>
                <input 
                  type="number" 
                  id="dealAmount" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }}
                  placeholder="e.g. 150000"
                  value={createForm.amount}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, amount: e.target.value }))}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="dealStage">Initial Stage</label>
                <select 
                  id="dealStage" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem', background: 'rgba(16, 19, 30, 0.9)' }}
                  value={createForm.stage}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, stage: e.target.value }))}
                >
                  <option value="Discovery">Discovery</option>
                  <option value="Proposal">Proposal</option>
                  <option value="Security Review">Security Review</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="dealCloseDate">Target Close Date</label>
                <input 
                  type="date" 
                  id="dealCloseDate" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }}
                  value={createForm.close_date}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, close_date: e.target.value }))}
                />
              </div>

              {createError && <div className="auth-alert auth-alert-error">{createError}</div>}

              <div className="dialog-footer">
                <button type="button" className="dialog-btn dialog-btn-cancel" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="dialog-btn dialog-btn-submit" disabled={createLoading}>
                  {createLoading ? "Creating..." : "Create Deal"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Deal Modal */}
      {showEditModal && (
        <div className="dialog-overlay">
          <div className="dialog-content">
            <div className="dialog-header">
              <h2 className="dialog-title">Edit Opportunity</h2>
              <button className="dialog-close-btn" onClick={() => setShowEditModal(false)}>
                <XCircle size={20} />
              </button>
            </div>

            <form className="dialog-form" onSubmit={async (e) => {
              e.preventDefault();
              setEditError(null);
              setEditLoading(true);
              try {
                await patchDealFields(editForm.id, {
                  name: editForm.name,
                  amount: parseFloat(editForm.amount),
                  stage: editForm.stage,
                  close_date: editForm.close_date,
                  confidence: editForm.confidence
                });
                setShowEditModal(false);
              } catch (err) {
                setEditError("Could not update deal.");
              } finally {
                setEditLoading(false);
              }
            }}>
              <div className="form-group">
                <label className="form-label" htmlFor="editDealName">Opportunity Name</label>
                <input 
                  type="text" 
                  id="editDealName" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }}
                  value={editForm.name}
                  onChange={(e) => setEditForm(prev => ({ ...prev, name: e.target.value }))}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="editDealAmount">Value (USD)</label>
                <input 
                  type="number" 
                  id="editDealAmount" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }}
                  value={editForm.amount}
                  onChange={(e) => setEditForm(prev => ({ ...prev, amount: e.target.value }))}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="editDealStage">Stage</label>
                <select 
                  id="editDealStage" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem', background: 'rgba(16, 19, 30, 0.9)' }}
                  value={editForm.stage}
                  onChange={(e) => setEditForm(prev => ({ ...prev, stage: e.target.value }))}
                >
                  <option value="Discovery">Discovery</option>
                  <option value="Proposal">Proposal</option>
                  <option value="Security Review">Security Review</option>
                  <option value="Closed-Won">Closed-Won</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="editDealCloseDate">Close Date</label>
                <input 
                  type="date" 
                  id="editDealCloseDate" 
                  className="form-input" 
                  style={{ paddingLeft: '1rem' }}
                  value={editForm.close_date}
                  onChange={(e) => setEditForm(prev => ({ ...prev, close_date: e.target.value }))}
                />
              </div>

              {editError && <div className="auth-alert auth-alert-error">{editError}</div>}

              <div className="dialog-footer">
                <button type="button" className="dialog-btn dialog-btn-cancel" onClick={() => setShowEditModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="dialog-btn dialog-btn-submit" disabled={editLoading}>
                  {editLoading ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
