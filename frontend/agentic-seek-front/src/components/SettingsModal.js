import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './SettingsModal.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export function SettingsModal({ isOpen, onClose }) {
  const [settings, setSettings] = useState({
    provider_name: 'lm-studio',
    provider_model: '',
    provider_server_address: 'http://127.0.0.1:1234',
    is_local: true
  });
  const [connectionStatus, setConnectionStatus] = useState({
    status: 'unknown',
    message: 'Not checked yet',
    models: []
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');

  useEffect(() => {
    if (isOpen) {
      fetchCurrentSettings();
    }
  }, [isOpen]);

  const fetchCurrentSettings = async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/llm/settings`);
      setSettings(res.data);
    } catch (error) {
      console.error('Error fetching settings:', error);
    }
  };

  const checkConnection = async () => {
    setIsLoading(true);
    setConnectionStatus({ status: 'checking', message: 'Checking connection...', models: [] });
    
    try {
      const res = await axios.post(`${BACKEND_URL}/llm/check-connection`, {
        provider_name: settings.provider_name,
        server_address: settings.provider_server_address
      });
      
      setConnectionStatus({
        status: res.data.connected ? 'connected' : 'disconnected',
        message: res.data.message,
        models: res.data.models || []
      });
    } catch (error) {
      setConnectionStatus({
        status: 'error',
        message: error.response?.data?.detail || 'Failed to check connection',
        models: []
      });
    } finally {
      setIsLoading(false);
    }
  };

  const saveSettings = async () => {
    setIsSaving(true);
    setSaveMessage('');
    
    try {
      await axios.post(`${BACKEND_URL}/llm/settings`, settings);
      setSaveMessage('Settings saved! Restart backend to apply changes.');
      setTimeout(() => setSaveMessage(''), 5000);
    } catch (error) {
      setSaveMessage('Error: ' + (error.response?.data?.detail || 'Failed to save settings'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleInputChange = (field, value) => {
    setSettings(prev => ({ ...prev, [field]: value }));
  };

  const selectModel = (modelName) => {
    setSettings(prev => ({ ...prev, provider_model: modelName }));
  };

  if (!isOpen) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={e => e.stopPropagation()}>
        <div className="settings-header">
          <h2>⚙️ LLM Provider Settings</h2>
          <button className="close-button" onClick={onClose}>×</button>
        </div>
        
        <div className="settings-content">
          {/* Provider Selection */}
          <div className="settings-group">
            <label>Provider</label>
            <select 
              value={settings.provider_name} 
              onChange={e => handleInputChange('provider_name', e.target.value)}
            >
              <option value="lm-studio">LM Studio</option>
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI (Local Compatible)</option>
            </select>
          </div>

          {/* Server Address */}
          <div className="settings-group">
            <label>Server Address</label>
            <input
              type="text"
              value={settings.provider_server_address}
              onChange={e => handleInputChange('provider_server_address', e.target.value)}
              placeholder="http://127.0.0.1:1234"
            />
            <span className="hint">
              {settings.provider_name === 'lm-studio' && 'Default: http://127.0.0.1:1234'}
              {settings.provider_name === 'ollama' && 'Default: 127.0.0.1:11434'}
            </span>
          </div>

          {/* Model Name */}
          <div className="settings-group">
            <label>Model Name</label>
            <input
              type="text"
              value={settings.provider_model}
              onChange={e => handleInputChange('provider_model', e.target.value)}
              placeholder="Enter model name (e.g., deepseek-r1)"
            />
            <span className="hint">Enter the exact model name as shown in LM Studio</span>
          </div>

          {/* Connection Status */}
          <div className="connection-section">
            <div className="connection-header">
              <h3>Connection Status</h3>
              <button 
                className="check-button"
                onClick={checkConnection}
                disabled={isLoading}
              >
                {isLoading ? '⏳ Checking...' : '🔍 Check Connection'}
              </button>
            </div>
            
            <div className={`connection-status status-${connectionStatus.status}`}>
              <div className="status-indicator">
                {connectionStatus.status === 'connected' && '✅'}
                {connectionStatus.status === 'disconnected' && '❌'}
                {connectionStatus.status === 'error' && '⚠️'}
                {connectionStatus.status === 'checking' && '⏳'}
                {connectionStatus.status === 'unknown' && '❓'}
              </div>
              <span className="status-message">{connectionStatus.message}</span>
            </div>

            {/* Available Models */}
            {connectionStatus.models.length > 0 && (
              <div className="models-list">
                <h4>Available Models (click to select):</h4>
                <div className="models-grid">
                  {connectionStatus.models.map((model, index) => (
                    <button
                      key={index}
                      className={`model-chip ${settings.provider_model === model ? 'selected' : ''}`}
                      onClick={() => selectModel(model)}
                    >
                      {model}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Is Local Toggle */}
          <div className="settings-group toggle-group">
            <label>
              <input
                type="checkbox"
                checked={settings.is_local}
                onChange={e => handleInputChange('is_local', e.target.checked)}
              />
              Running locally (not cloud API)
            </label>
          </div>
        </div>

        <div className="settings-footer">
          {saveMessage && (
            <span className={`save-message ${saveMessage.includes('Error') ? 'error' : 'success'}`}>
              {saveMessage}
            </span>
          )}
          <button className="cancel-button" onClick={onClose}>Cancel</button>
          <button 
            className="save-button" 
            onClick={saveSettings}
            disabled={isSaving}
          >
            {isSaving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
