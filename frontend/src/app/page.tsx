'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  PhoneCall, 
  PhoneOff, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  Terminal, 
  Activity, 
  Briefcase, 
  Clock, 
  DollarSign, 
  User 
} from 'lucide-react';
import { LiveKitRoom, RoomAudioRenderer, useRoomContext } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';

// Constants
const LIVEKIT_URL = "wss://signalops-rjjzu2g7.livekit.cloud";
const BACKEND_API = "http://127.0.0.1:8000";

// --- Subcomponent: LiveKit event hook & data channel parser ---
function DataChannelListener({ 
  onTranscript, 
  onFact, 
  onSummary,
  onDisconnect 
}: { 
  onTranscript: (role: string, text: string) => void;
  onFact: (fact: { type: string; value: string; confidence: number }) => void;
  onSummary: (summary: any) => void;
  onDisconnect: () => void;
}) {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handleDataReceived = (payload: Uint8Array, participant: any) => {
      const decoder = new TextDecoder();
      const str = decoder.decode(payload);
      try {
        const data = JSON.parse(str);
        console.log("Received WebRTC Data Channel Event:", data);
        
        if (data.type === "TRANSCRIPT") {
          onTranscript(data.role, data.text);
        } else if (data.type === "TOOL_EXECUTION") {
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
  }, [room, onTranscript, onFact, onSummary, onDisconnect]);

  return null;
}

// --- Main Page Component ---
export default function Page() {
  // Call states
  const [ringing, setRinging] = useState(false);
  const [roomName, setRoomName] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [callActive, setCallActive] = useState(false);
  const [backendConnected, setBackendConnected] = useState(false);

  // CRM & Checklist states (Dynamic UI updates from AI tools)
  const [checklist, setChecklist] = useState([
    { id: 'context', text: 'Pipeline context and AE identity confirmed', status: 'pending' }, // pending | checked | delayed
    { id: 'blocker', text: 'Primary deal blocker identified', status: 'pending' },
    { id: 'security_docs', text: 'Prepare and deliver security architecture documents', status: 'pending' },
    { id: 'stakeholder', text: 'Confirm Rohit (Economic Buyer) meeting status', status: 'pending' },
    { id: 'summary', text: 'Persist findings and facts back to CRM', status: 'pending' }
  ]);
  const [crmFacts, setCrmFacts] = useState<Array<{ time: string; msg: string }>>([]);
  const [transcripts, setTranscripts] = useState<Array<{ id: string; role: string; text: string }>>([]);
  const [summary, setSummary] = useState<any | null>(null);

  // Poll server for trigger status
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
  }, []);

  // Accept inbound call and fetch LiveKit token
  const handleAcceptCall = async () => {
    if (!roomName) return;
    try {
      // Clear the ringing state on the backend to stop the polling loop from showing the modal
      try {
        await fetch(`${BACKEND_API}/api/clear`, { method: 'POST' });
      } catch (err) {
        console.error("Failed to clear ringing state on backend:", err);
      }

      const res = await fetch(`${BACKEND_API}/api/token?room=${roomName}&identity=Aarav`);
      if (res.ok) {
        const data = await res.json();
        setToken(data.token);
        setCallActive(true);
        setRinging(false);
        
        // Reset call variables
        setTranscripts([]);
        setSummary(null);
        setCrmFacts([]);
        setChecklist([
          { id: 'context', text: 'Pipeline context and AE identity confirmed', status: 'checked' },
          { id: 'blocker', text: 'Primary deal blocker identified', status: 'pending' },
          { id: 'security_docs', text: 'Prepare and deliver security architecture documents', status: 'pending' },
          { id: 'stakeholder', text: 'Confirm Rohit (Economic Buyer) meeting status', status: 'pending' },
          { id: 'summary', text: 'Persist findings and facts back to CRM', status: 'pending' }
        ]);

        // Append log to CRM
        addCrmLog("System", "Call accepted. AE connected to Room.");
      }
    } catch (e) {
      console.error("Error connecting to call:", e);
    }
  };

  // Decline or disconnect call
  const handleDeclineOrDisconnect = async () => {
    setCallActive(false);
    setToken(null);
    setRinging(false);
    try {
      await fetch(`${BACKEND_API}/api/clear`, { method: 'POST' });
    } catch (e) {
      console.error("Failed to clear trigger status:", e);
    }
    addCrmLog("System", "Call session terminated.");
  };

  // Trigger test call mock endpoint
  const handleTriggerTestCall = async () => {
    try {
      const randomRoom = `room_${Math.floor(Date.now() / 1000)}`;
      await fetch(`${BACKEND_API}/api/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_name: randomRoom })
      });
      setRoomName(randomRoom);
      setRinging(true);
    } catch (e) {
      console.error("Failed to trigger call:", e);
    }
  };

  // Helper log functions
  const addCrmLog = (source: string, msg: string) => {
    const timeStr = new Date().toLocaleTimeString();
    setCrmFacts(prev => [{ time: timeStr, msg: `[${source}] ${msg}` }, ...prev]);
  };

  // Callback: Handle transcript streaming from agent
  const handleTranscriptReceived = useCallback((role: string, text: string) => {
    setTranscripts(prev => {
      // If the last speech is from the same role, replace or append text chunks
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

    // Reactively update checklist based on what's being said
    if (role === "user" && text.toLowerCase().includes("waiting on security")) {
      updateChecklistStatus("blocker", "checked");
    }
  }, []);

  // Callback: Handle facts dynamically captured by AI tools
  const handleFactReceived = useCallback((fact: { type: string; value: string; confidence: number }) => {
    addCrmLog("AI Agent (append_call_fact)", `Fact recorded: ${fact.type}="${fact.value}" (confidence=${fact.confidence.toFixed(1)})`);

    // Dynamic Checklist checklist updates
    if (fact.value.toLowerCase().includes("documents not prepared") || fact.value.toLowerCase().includes("documents not sent")) {
      updateChecklistStatus("security_docs", "delayed");
    }
    if (fact.value.toLowerCase().includes("responsible")) {
      updateChecklistStatus("security_docs", "checked");
    }
  }, []);

  // Callback: Handle final call summary saved by AI at the end
  const handleSummaryReceived = useCallback((summaryData: any) => {
    addCrmLog("AI Agent (save_call_summary)", `Summary Saved: "${summaryData.primary_blocker}"`);
    setSummary(summaryData);
    
    // Check off remaining checklist
    updateChecklistStatus("summary", "checked");
    updateChecklistStatus("stakeholder", summaryData.evidence.some((e: string) => e.toLowerCase().includes("buyer") || e.toLowerCase().includes("rohit")) ? "checked" : "delayed");
  }, []);

  // Helper: Update checklist item state
  const updateChecklistStatus = (id: string, status: 'checked' | 'delayed' | 'pending') => {
    setChecklist(prev => prev.map(item => item.id === id ? { ...item, status } : item));
  };

  return (
    <div className="dashboard-container">
      {/* Header Panel */}
      <div className="header">
        <div className="logo-section">
          <h1>
            <span className="logo-dot"></span> SignalOps Revenue Intelligence
          </h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '8px', 
              height: '8px', 
              borderRadius: '50%', 
              backgroundColor: backendConnected ? 'var(--accent-emerald)' : 'var(--accent-rose)' 
            }}></span>
            <span style={{ color: 'var(--text-secondary)' }}>
              {backendConnected ? "Backend Connected" : "Backend Disconnected"}
            </span>
          </div>
          
          <button className="trigger-btn" onClick={handleTriggerTestCall}>
            <PhoneCall size={16} /> Simulate Inbound Call
          </button>
        </div>
      </div>

      {/* Main Grid */}
      <div className="dashboard-grid">
        
        {/* LEFT COLUMN: Deal Context, Checklist, and AI Call panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          
          {/* Card: Acme Renewal expansion Opportunity */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Deal Review: Acme Renewal Expansion</div>
              <span className="badge badge-info">Proposal Stage</span>
            </div>
            
            <div className="deal-details-layout">
              <div className="deal-stat">
                <div className="deal-stat-label">Value</div>
                <div className="deal-stat-value" style={{ color: 'var(--accent-cyan)' }}>$180,000</div>
              </div>
              <div className="deal-stat">
                <div className="deal-stat-label">Representative</div>
                <div className="deal-stat-value">Aarav (Enterprise East)</div>
              </div>
              <div className="deal-stat">
                <div className="deal-stat-label">Close Date</div>
                <div className="deal-stat-value">June 18, 2026</div>
              </div>
              <div className="deal-stat">
                <div className="deal-stat-label">Close Date Changes</div>
                <div className="deal-stat-value" style={{ color: 'var(--accent-orange)' }}>4 in 90 Days</div>
              </div>
            </div>

            <div>
              <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>Checklist Status</h4>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {checklist.map(item => (
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
                    {item.status === 'delayed' && (
                      <span className="badge badge-rose" style={{ marginLeft: 'auto', fontSize: '0.65rem' }}>Delayed</span>
                    )}
                    {item.status === 'checked' && (
                      <span className="badge badge-success" style={{ marginLeft: 'auto', fontSize: '0.65rem' }}>Verified</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Card: Active Call and Live Transcription panel */}
          {callActive && token && (
            <div className="card" style={{ flex: 1 }}>
              <div className="card-header">
                <div className="card-title">Live Revenue Review Session</div>
                <span className="badge badge-rose" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                  <span style={{ 
                    width: '6px', 
                    height: '6px', 
                    borderRadius: '50%', 
                    backgroundColor: 'white',
                    animation: 'fadeIn 0.8s infinite alternate'
                  }}></span>
                  Live Connection
                </span>
              </div>

              <div className="active-call-panel">
                <div className="transcription-feed">
                  {transcripts.length === 0 && (
                    <div style={{ color: 'var(--text-muted)', textAlign: 'center', margin: 'auto' }}>
                      Connecting audio channel... Agent will speak greeting.
                    </div>
                  )}
                  {transcripts.map(t => (
                    <div key={t.id} className={`speech-bubble ${t.role === 'user' ? 'bubble-user' : 'bubble-agent'}`}>
                      <span className={`bubble-sender ${t.role === 'user' ? 'bubble-sender-user' : 'bubble-sender-agent'}`}>
                        {t.role === 'user' ? 'Aarav' : 'AI Revenue Operations'}
                      </span>
                      {t.text}
                    </div>
                  ))}
                </div>

                {/* Sound wave Visualizer and Hangup */}
                <div className="waveform-section">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <div className="sound-wave-visualizer">
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                      <div className="sound-wave-bar"></div>
                    </div>
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Microphone Active</span>
                  </div>
                  <button className="call-btn-disconnect" onClick={handleDeclineOrDisconnect}>
                    End Interview
                  </button>
                </div>
              </div>

              {/* Hook up LiveKit Audio Stream and Listener */}
              <LiveKitRoom
                video={false}
                audio={true}
                token={token}
                serverUrl={LIVEKIT_URL}
                connect={true}
                data-lk-theme="default"
              >
                <RoomAudioRenderer />
                <DataChannelListener
                  onTranscript={handleTranscriptReceived}
                  onFact={handleFactReceived}
                  onSummary={handleSummaryReceived}
                  onDisconnect={() => setCallActive(false)}
                />
              </LiveKitRoom>
            </div>
          )}

        </div>

        {/* RIGHT COLUMN: AI Agent Logs and CRM summary updates */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          
          {/* Card: Real-time telemetry log */}
          <div className="card" style={{ flex: 1 }}>
            <div className="card-header">
              <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Activity size={18} style={{ color: 'var(--accent-cyan)' }} /> 
                CRM Activity Feed
              </div>
            </div>
            
            <div className="action-log-feed">
              {crmFacts.length === 0 && (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  No active logs. Start or simulate a review call.
                </div>
              )}
              {crmFacts.map((log, index) => (
                <div className="action-log-item" key={index}>
                  <div className="action-log-time">{log.time}</div>
                  <div className="action-log-msg">{log.msg}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Card: persistent CRM Summarized Deal context (Shown on save_call_summary) */}
          {summary && (
            <div className="card crm-summary-card">
              <div className="card-header" style={{ borderColor: 'rgba(5, 213, 144, 0.2)' }}>
                <div className="card-title" style={{ color: 'var(--accent-emerald)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={18} /> CRM Persisted Summary
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.9rem' }}>
                <div>
                  <strong>Primary Blocker:</strong>
                  <div style={{ color: 'var(--text-primary)', marginTop: '0.2rem' }}>{summary.primary_blocker}</div>
                </div>
                <div>
                  <strong>Root Cause:</strong>
                  <div style={{ color: 'var(--text-primary)', marginTop: '0.2rem' }}>{summary.root_cause}</div>
                </div>
                <div>
                  <strong>AI Confidence:</strong>
                  <span style={{ color: 'var(--accent-cyan)', marginLeft: '0.5rem' }}>{(summary.confidence * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <strong>Logged Evidence:</strong>
                  <ul className="crm-summary-evidence">
                    {summary.evidence?.map((item: string, idx: number) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

        </div>

      </div>

      {/* Ringing Modal (Rings until answered) */}
      {ringing && (
        <div className="ringing-modal-overlay">
          <div className="ringing-card">
            <div className="ringing-phone-icon">
              <PhoneCall size={36} />
            </div>
            <div className="caller-info">
              <h2>Incoming Interview Call</h2>
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
    </div>
  );
}
