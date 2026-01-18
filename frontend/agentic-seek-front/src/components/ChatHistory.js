import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './ChatHistory.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export const ChatHistory = ({ isOpen, onClose, onSessionLoad, onNewSession }) => {
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedSession, setSelectedSession] = useState(null);
    const [actionLoading, setActionLoading] = useState(null);

    const fetchSessions = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(`${BACKEND_URL}/sessions`);
            setSessions(res.data.sessions || []);
        } catch (err) {
            console.error('Error fetching sessions:', err);
            setError('Failed to load chat history');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (isOpen) {
            fetchSessions();
        }
    }, [isOpen, fetchSessions]);

    const handleNewSession = async () => {
        setActionLoading('new');
        try {
            const res = await axios.post(`${BACKEND_URL}/sessions/new`);
            if (res.data.status === 'new_session_created') {
                onNewSession && onNewSession(res.data.session_id);
                fetchSessions();
            }
        } catch (err) {
            console.error('Error creating new session:', err);
            setError('Failed to create new session');
        } finally {
            setActionLoading(null);
        }
    };

    const handleLoadSession = async (sessionId) => {
        setActionLoading(sessionId);
        try {
            const res = await axios.post(`${BACKEND_URL}/sessions/${sessionId}/load`);
            if (res.data.status === 'session_loaded') {
                onSessionLoad && onSessionLoad(sessionId, res.data);
                setSelectedSession(sessionId);
            }
        } catch (err) {
            console.error('Error loading session:', err);
            setError('Failed to load session');
        } finally {
            setActionLoading(null);
        }
    };

    const handleDeleteSession = async (e, sessionId) => {
        e.stopPropagation();
        if (!window.confirm('Are you sure you want to delete this session?')) {
            return;
        }
        setActionLoading(`delete-${sessionId}`);
        try {
            await axios.delete(`${BACKEND_URL}/sessions/${sessionId}`);
            fetchSessions();
        } catch (err) {
            console.error('Error deleting session:', err);
            setError('Failed to delete session');
        } finally {
            setActionLoading(null);
        }
    };

    const formatDate = (sessionId) => {
        try {
            // sessionId format: YYYY-MM-DD_HH-MM-SS
            const [datePart, timePart] = sessionId.split('_');
            const [year, month, day] = datePart.split('-');
            const [hour, minute] = timePart.split('-');
            const date = new Date(year, month - 1, day, hour, minute);

            const now = new Date();
            const diffDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));

            if (diffDays === 0) return 'Today';
            if (diffDays === 1) return 'Yesterday';
            if (diffDays < 7) return `${diffDays} days ago`;
            return date.toLocaleDateString();
        } catch {
            return sessionId;
        }
    };

    const formatTime = (sessionId) => {
        try {
            const [, timePart] = sessionId.split('_');
            const [hour, minute] = timePart.split('-');
            return `${hour}:${minute}`;
        } catch {
            return '';
        }
    };

    if (!isOpen) return null;

    return (
        <div className="chat-history-overlay" onClick={onClose}>
            <div className="chat-history-sidebar" onClick={(e) => e.stopPropagation()}>
                <div className="chat-history-header">
                    <h2>Chat History</h2>
                    <button className="close-button" onClick={onClose}>×</button>
                </div>

                <div className="chat-history-actions">
                    <button
                        className="new-chat-button"
                        onClick={handleNewSession}
                        disabled={actionLoading === 'new'}
                    >
                        {actionLoading === 'new' ? (
                            <span className="loading-spinner-small"></span>
                        ) : (
                            <>
                                <span className="plus-icon">+</span>
                                New Chat
                            </>
                        )}
                    </button>
                </div>

                {error && (
                    <div className="chat-history-error">
                        {error}
                        <button onClick={() => setError(null)}>×</button>
                    </div>
                )}

                <div className="chat-history-list">
                    {loading ? (
                        <div className="loading-container">
                            <div className="loading-spinner"></div>
                            <p>Loading sessions...</p>
                        </div>
                    ) : sessions.length === 0 ? (
                        <div className="empty-state">
                            <p>No chat history yet</p>
                            <p className="empty-hint">Start a conversation to create your first session</p>
                        </div>
                    ) : (
                        sessions.map((session) => (
                            <div
                                key={session.session_id}
                                className={`session-item ${selectedSession === session.session_id ? 'selected' : ''}`}
                                onClick={() => handleLoadSession(session.session_id)}
                            >
                                <div className="session-info">
                                    <div className="session-date">
                                        <span className="date-label">{formatDate(session.session_id)}</span>
                                        <span className="time-label">{formatTime(session.session_id)}</span>
                                    </div>
                                    <div className="session-preview">
                                        {session.preview || 'No preview available'}
                                    </div>
                                    <div className="session-meta">
                                        <span className="message-count">{session.message_count} messages</span>
                                    </div>
                                </div>
                                <div className="session-actions">
                                    {actionLoading === session.session_id ? (
                                        <span className="loading-spinner-small"></span>
                                    ) : (
                                        <button
                                            className="delete-button"
                                            onClick={(e) => handleDeleteSession(e, session.session_id)}
                                            disabled={actionLoading === `delete-${session.session_id}`}
                                            title="Delete session"
                                        >
                                            🗑️
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))
                    )}
                </div>

                <div className="chat-history-footer">
                    <button onClick={fetchSessions} className="refresh-button">
                        🔄 Refresh
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ChatHistory;
