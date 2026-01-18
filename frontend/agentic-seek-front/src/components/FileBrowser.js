import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './FileBrowser.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export const FileBrowser = ({ isOpen, onClose }) => {
    const [currentPath, setCurrentPath] = useState('');
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [viewingFile, setViewingFile] = useState(null);
    const [fileContent, setFileContent] = useState(null);

    const fetchFiles = useCallback(async (path = '') => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(`${BACKEND_URL}/files`, { params: { path } });
            setItems(res.data.items || []);
            setCurrentPath(res.data.path || '');
        } catch (err) {
            console.error('Error fetching files:', err);
            setError('Failed to load files');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (isOpen) {
            fetchFiles();
        }
    }, [isOpen, fetchFiles]);

    const handleItemClick = async (item) => {
        if (item.is_dir) {
            fetchFiles(item.path);
        } else {
            // View file
            setLoading(true);
            try {
                const res = await axios.get(`${BACKEND_URL}/files/view`, { params: { path: item.path } });
                setViewingFile(item);
                setFileContent(res.data);
            } catch (err) {
                if (err.response?.data?.error === 'Binary file cannot be viewed as text') {
                    // Offer download instead
                    handleDownload(item);
                } else {
                    setError(err.response?.data?.error || 'Failed to view file');
                }
            } finally {
                setLoading(false);
            }
        }
    };

    const handleDownload = (item) => {
        window.open(`${BACKEND_URL}/files/download?path=${encodeURIComponent(item.path)}`, '_blank');
    };

    const handleBack = () => {
        if (viewingFile) {
            setViewingFile(null);
            setFileContent(null);
        } else if (currentPath) {
            const parentPath = currentPath.split('/').slice(0, -1).join('/');
            fetchFiles(parentPath);
        }
    };

    const formatSize = (bytes) => {
        if (bytes === null) return '-';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const formatDate = (timestamp) => {
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    };

    if (!isOpen) return null;

    return (
        <div className="file-browser-overlay" onClick={onClose}>
            <div className="file-browser-modal" onClick={(e) => e.stopPropagation()}>
                <div className="file-browser-header">
                    <h2>📁 Workspace Files</h2>
                    <button className="close-button" onClick={onClose}>×</button>
                </div>

                <div className="file-browser-nav">
                    <button
                        className="nav-button"
                        onClick={handleBack}
                        disabled={!currentPath && !viewingFile}
                    >
                        ← Back
                    </button>
                    <span className="current-path">
                        /workspace/{currentPath || ''}
                    </span>
                    {!viewingFile && (
                        <button className="nav-button" onClick={() => fetchFiles(currentPath)}>
                            🔄 Refresh
                        </button>
                    )}
                </div>

                {error && (
                    <div className="file-browser-error">
                        {error}
                        <button onClick={() => setError(null)}>×</button>
                    </div>
                )}

                <div className="file-browser-content">
                    {loading ? (
                        <div className="loading-container">
                            <div className="loading-spinner"></div>
                            <p>Loading...</p>
                        </div>
                    ) : viewingFile ? (
                        <div className="file-viewer">
                            <div className="file-viewer-header">
                                <span className="file-name">{fileContent?.name}</span>
                                <span className="file-meta">{formatSize(fileContent?.size)} • {fileContent?.type}</span>
                                <button
                                    className="download-button"
                                    onClick={() => handleDownload(viewingFile)}
                                >
                                    ⬇️ Download
                                </button>
                            </div>
                            <pre className="file-content">
                                <code>{fileContent?.content}</code>
                            </pre>
                        </div>
                    ) : items.length === 0 ? (
                        <div className="empty-state">
                            <p>No files in this directory</p>
                        </div>
                    ) : (
                        <div className="file-list">
                            {items.map((item, index) => (
                                <div
                                    key={index}
                                    className={`file-item ${item.is_dir ? 'directory' : 'file'}`}
                                    onClick={() => handleItemClick(item)}
                                >
                                    <span className="file-icon">
                                        {item.is_dir ? '📁' : '📄'}
                                    </span>
                                    <span className="file-name">{item.name}</span>
                                    <span className="file-size">{formatSize(item.size)}</span>
                                    <span className="file-date">{formatDate(item.modified)}</span>
                                    {!item.is_dir && (
                                        <button
                                            className="download-btn"
                                            onClick={(e) => { e.stopPropagation(); handleDownload(item); }}
                                            title="Download"
                                        >
                                            ⬇️
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default FileBrowser;
