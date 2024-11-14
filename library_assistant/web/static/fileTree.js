import React, { useState, useEffect } from 'react';

// Override console.log to send logs to the server
(function() {
    const originalLog = console.log;
    console.log = function(...args) {
        originalLog.apply(console, args);
        fetch('/api/log', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: args.join(' ') })
        }).catch(error => originalLog('Error sending log:', error));
    };
})();

// File node component
const FileNode = ({ file, path, onSelect, isSelected }) => (
  <div className="file ps-3">
    <div className="d-flex align-items-center py-1 hover-bg-light">
      <input 
        type="checkbox" 
        className="form-check-input me-2"
        checked={isSelected}
        onChange={(e) => onSelect(path, file.tokens, e.target.checked)}
      />
      <span className="me-2">📄</span>
      <span>{file.name}</span>
      <small className="text-muted ms-2">({file.tokens?.toLocaleString() || 0} tokens)</small>
    </div>
  </div>
);

// Folder node component
const FolderNode = ({ folder, path, expanded, onToggle, children }) => (
  <div className="folder ps-3">
    <div className="d-flex align-items-center py-1 hover-bg-light">
      <button 
        className="btn btn-sm p-0 me-2"
        onClick={() => onToggle(path)}
      >
        {expanded ? '▼' : '▶'}
      </button>
      <span className="me-2">📁</span>
      <span>{folder.name}</span>
      <small className="text-muted ms-2">({folder.tokens?.toLocaleString() || 0} tokens)</small>
    </div>
    {expanded && <div className="children ps-3">{children}</div>}
  </div>
);

// Stats display component
const StatsDisplay = ({ stats, tokens }) => (
  <div className="p-3 bg-gray-100 rounded border sticky-bottom">
    <div className="mb-2 border-bottom pb-2">
      <div className="d-flex justify-content-between">
        <span>Selected Files:</span>
        <strong>{stats.fileCount} files</strong>
      </div>
      <div className="d-flex justify-content-between">
        <span>Selected Tokens:</span>
        <strong>{stats.tokens.toLocaleString()}</strong>
      </div>
    </div>
    <div>
      <div className="fw-bold mb-1">Estimated Context Costs:</div>
      <div className="d-flex justify-content-between">
        <span>Claude 3.5:</span>
        <strong>${stats.costs.claude.toFixed(4)}</strong>
      </div>
      <div className="d-flex justify-content-between">
        <span>GPT-4:</span>
        <strong>${stats.costs.gpt4.toFixed(4)}</strong>
      </div>
      <div className="d-flex justify-content-between">
        <span>GPT-4 Mini:</span>
        <strong>${stats.costs.gpt4mini.toFixed(4)}</strong>
      </div>
      <div className="mt-2 pt-2 border-top">
        <div className="d-flex justify-content-between text-muted">
          <small>Current Conversation:</small>
          <small>{tokens.conversation.toLocaleString()} tokens</small>
        </div>
        <div className="d-flex justify-content-between text-muted">
          <small>Message Being Typed:</small>
          <small>{tokens.currentMessage.toLocaleString()} tokens</small>
        </div>
      </div>
    </div>
  </div>
);

// Main FileTreeViewer component
const FileTreeViewer = ({ initialData }) => {
  const [fileData, setFileData] = useState(initialData);
  const [selectedFiles, setSelectedFiles] = useState(new Set());
  const [expandedFolders, setExpandedFolders] = useState(new Set(['library_assistant']));
  const [fileContents, setFileContents] = useState(new Map());
  const [tokens, setTokens] = useState({ conversation: 0, currentMessage: 0 });
  const [statsUpdate, setStatsUpdate] = useState(0);

  // Handle file selection and deselection
  const handleFileSelect = async (path, tokens, selected) => {
    console.group(`handleFileSelect: ${path}`);
    console.log('Selected:', selected);
    console.log('Tokens:', tokens);
    
    if (selected) {
        try {
            console.log('Fetching file content...');
            const content = await getFileContent(path);
            console.log('Content received:', !!content);
            
            if (content) {
                setSelectedFiles(prev => {
                    const next = new Set([...prev, path]);
                    console.log('Updated selected files:', Array.from(next));
                    return next;
                });
                setFileContents(prev => new Map(prev).set(path, content));
            }
        } catch (error) {
            console.error('Error loading file:', error);
        }
    } else {
        setSelectedFiles(prev => {
            const next = new Set(prev);
            next.delete(path);
            console.log('Updated selected files after removal:', Array.from(next));
            return next;
        });
    }
    
    setStatsUpdate(prev => prev + 1);
    console.groupEnd();
  };

  // Handle folder expansion
  const handleFolderToggle = (path) => {
    setExpandedFolders(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  // Fetch file content
  const getFileContent = async (path) => {
    if (fileContents.has(path)) {
      return fileContents.get(path);
    }

    const response = await fetch(`/get_file_content?path=${encodeURIComponent(path)}`);
    if (!response.ok) throw new Error('Failed to fetch file content');
    
    return await response.json();
  };

  // Render the file tree
  const renderTree = (item, path = '') => {
    const fullPath = path ? `${path}/${item.name}` : item.name;
    console.group(`renderTree: ${fullPath}`);
    console.log('Item:', item);
    console.log('Current path:', path);
    console.log('Full path:', fullPath);
    
    let result;
    if (item.type === 'directory') {
        const isExpanded = expandedFolders.has(fullPath);
        console.log('Directory is expanded:', isExpanded);
        result = (
            <FolderNode
                key={fullPath}
                folder={item}
                path={fullPath}
                expanded={isExpanded}
                onToggle={handleFolderToggle}
            >
                {isExpanded && item.children?.map(child => renderTree(child, fullPath))}
            </FolderNode>
        );
    } else {
        const isSelected = selectedFiles.has(fullPath);
        console.log('File is selected:', isSelected);
        result = (
            <FileNode
                key={fullPath}
                file={item}
                path={fullPath}
                isSelected={isSelected}
                onSelect={handleFileSelect}
            />
        );
    }
    
    console.groupEnd();
    return result;
  };

  useEffect(() => {
    console.group('FileTreeViewer Initialization');
    console.log('Initial data:', initialData);
    console.log('File data structure:', fileData);
    console.groupEnd();
  }, [initialData, fileData]);

  const updateDisplays = () => {
    document.getElementById('selected-files-count').textContent = `${selectedFiles.size} files`;
    document.getElementById('selected-tokens-count').textContent = calculateStats().tokens.toLocaleString();
    // Update cost displays
    document.getElementById('claude-cost').textContent = `$${calculateStats().costs.claude.toFixed(4)}`;
    document.getElementById('gpt4-cost').textContent = `$${calculateStats().costs.gpt4.toFixed(4)}`;
    document.getElementById('gpt4-mini-cost').textContent = `$${calculateStats().costs.gpt4mini.toFixed(4)}`;
  };

  useEffect(() => {
    updateDisplays();
  }, [selectedFiles, statsUpdate]);

  return (
    <div className="file-tree-container">
      <div className="file-tree-header">
        <div className="d-flex justify-content-between align-items-center w-100">
          <h5 className="mb-0">Project Files</h5>
          <button className="btn btn-sm btn-primary" onClick={() => window.location.reload()}>
            <span className="refresh-icon">↻</span> Refresh Context
          </button>
        </div>
      </div>
      <div className="file-tree">
        {fileData && renderTree(fileData)}
      </div>
      <StatsDisplay key={statsUpdate} stats={calculateStats()} tokens={tokens} />
    </div>
  );
};

export default FileTreeViewer;