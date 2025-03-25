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
const FileNode = ({ file, path, onSelect, isSelected, isOmitted }) => (
  <div className={`file ps-3 ${isOmitted ? 'omitted' : ''}`}>
    <div className="d-flex align-items-center py-1 hover-bg-light">
      {!isOmitted && (
        <input 
          type="checkbox" 
          className="form-check-input me-2"
          checked={isSelected}
          onChange={(e) => onSelect(path, file.tokens, e.target.checked)}
        />
      )}
      <span className="me-2">📄</span>
      <span>{file.name}</span>
      {!isOmitted && (
        <span className="token-count badge bg-light text-dark">
          {file.tokens?.toLocaleString() || 0} tokens
        </span>
      )}
    </div>
  </div>
);

// Folder node component
const FolderNode = ({ folder, path, expanded, onToggle, children, isOmitted }) => (
  <div className={`folder ps-3 ${isOmitted ? 'omitted' : ''}`}>
    <div className="d-flex align-items-center py-1 hover-bg-light">
      <button 
        className="btn btn-sm p-0 me-2"
        onClick={() => onToggle(path)}
      >
        {expanded ? '▼' : '▶'}
      </button>
      <span className="me-2">📁</span>
      <span>{folder.name}</span>
      {!isOmitted && (
        <span className="token-count badge bg-light text-dark">
          {folder.tokens?.toLocaleString() || 0} tokens
        </span>
      )}
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
        <strong>{tokens.conversation.toLocaleString()}</strong>
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
          
          // Trigger token update after file selection changes
          if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
            updateTokenDisplay();
          }
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
      fileContents.delete(path);
      
      // Trigger token update after file selection changes
      if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
        updateTokenDisplay();
      }
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

  // Check if a path is in omitted folders
  const isOmittedPath = (path) => {
    const omittedFolders = JSON.parse(document.getElementById('omitted-folders').value || '[]');
    return omittedFolders.some(folder => path.includes(folder));
  };

  // Render the file tree
  const renderTree = (item, path = '') => {
    const fullPath = path ? `${path}/${item.name}` : item.name;
    console.group(`renderTree: ${fullPath}`);
    console.log('Item:', item);
    console.log('Current path:', path);
    console.log('Full path:', fullPath);
    
    const isOmitted = isOmittedPath(fullPath);
    
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
                isOmitted={isOmitted}
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
                isOmitted={isOmitted}
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

  // Effect to update token display when files change
  React.useEffect(() => {
    const updateTokens = async () => {
      if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
        try {
          const selectedContents = await getSelectedFilesContent();
          const userInput = document.getElementById('user-input')?.value || '';
          const modelName = document.getElementById('selected_model')?.value || '';
          const systemMessage = document.getElementById('system-message')?.value || '';
          
          const response = await fetch('/calculate_tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model_name: modelName,
              conversation_history: getConversationHistory(),
              user_input: userInput,
              rag_context: selectedContents.join('\n'),
              system_message: systemMessage,
              output_length: parseInt(document.getElementById('output_length')?.value) || null
            })
          });
          
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }
          
          const data = await response.json();
          if (data && typeof data === 'object') {
            window.updateTokenDisplays(data);
          }
        } catch (error) {
          console.error('Error updating tokens:', error);
        }
      }
    };
    
    updateTokens();
  }, [selectedFiles, fileContents]);

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