/**
 * main.js
 *
 * Contains the vanilla JS for:
 *   - Chat submission (SSE streaming)
 *   - File tree viewer logic
 *   - Auto-saving settings
 *   - Resetting conversation
 *   - Saving conversation to a file
 */

let debounceTimer = null;

// Chat form logic
document.addEventListener('DOMContentLoaded', () => {
  const chatForm = document.getElementById('chat-form');
  const userInputArea = document.getElementById('user-input');
  const chatBox = document.getElementById('chat-box');
  const loadingDots = document.querySelector('.loading-dots');
  const systemMessageEl = document.getElementById('system-message');
  const selectedModelEl = document.getElementById('selected_model');
  const outputLengthEl = document.getElementById('output_length');

  if (chatForm) {
    chatForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const messageContent = userInputArea.value.trim();
      if (!messageContent) return;

      // Show loading animation
      loadingDots.classList.add('active');

      // Display user message
      const userMessageDiv = document.createElement('div');
      userMessageDiv.className = 'message user';
      userMessageDiv.innerHTML = 'User: ' + marked.parse(messageContent);
      chatBox.appendChild(userMessageDiv);

      // Clear input
      userInputArea.value = '';

      // Create assistant message container
      const assistantMessage = document.createElement('div');
      assistantMessage.className = 'message assistant';
      assistantMessage.innerHTML = 'Assistant: ';
      const responseText = document.createElement('span');
      assistantMessage.appendChild(responseText);
      chatBox.appendChild(assistantMessage);

      // Scroll to bottom
      chatBox.scrollTop = chatBox.scrollHeight;

      try {
        // Gather selected files
        const selectedFiles = window.fileTreeViewer
          ? [...window.fileTreeViewer.selectedFiles]
          : [];

        // SSE request
        const response = await fetch('/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
          },
          body: JSON.stringify({
            message: messageContent,
            selectedFiles: selectedFiles,
            conversation_id: Date.now().toString()
          })
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Stream reading
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullResponse = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.chunk) {
                  fullResponse += data.chunk;
                  responseText.innerHTML = marked.parse(fullResponse);
                  chatBox.scrollTop = chatBox.scrollHeight;
                } else if (data.cost) {
                  // Append copy button
                  const copyButton = document.createElement('button');
                  copyButton.textContent = 'Copy Response';
                  copyButton.className = 'copy-btn btn btn-sm ms-2';
                  copyButton.onclick = () => copyToClipboard(fullResponse);
                  assistantMessage.appendChild(copyButton);
                } else if (data.error) {
                  // Improve error display
                  const errorDiv = document.createElement('div');
                  errorDiv.className = 'error-message alert alert-danger mt-2';
                  errorDiv.innerHTML = `<strong>Error:</strong> ${data.error}`;
                  assistantMessage.appendChild(errorDiv);
                  
                  // Add a retry button
                  const retryButton = document.createElement('button');
                  retryButton.textContent = 'Retry';
                  retryButton.className = 'btn btn-sm btn-outline-danger mt-2';
                  retryButton.onclick = () => {
                    // Re-submit the same message
                    userInputArea.value = messageContent;
                    // Remove the current assistant message
                    chatBox.removeChild(assistantMessage);
                    // Remove the user message to prevent duplicates
                    chatBox.removeChild(userMessageDiv);
                    // Submit the form again
                    chatForm.dispatchEvent(new Event('submit'));
                  };
                  assistantMessage.appendChild(retryButton);
                }
              } catch (err) {
                console.error('Error parsing SSE data:', err);
              }
            }
          }
        }
      } catch (error) {
        console.error('Error:', error);
        // Improve the error message display for fetch/connection errors
        const errorMessage = document.createElement('div');
        errorMessage.className = 'message assistant';
        errorMessage.innerHTML = 'Assistant: <div class="error-message alert alert-danger mt-2"><strong>Connection Error:</strong> ' + error.message + '</div>';
        
        // Add a retry button for connection errors too
        const retryButton = document.createElement('button');
        retryButton.textContent = 'Retry';
        retryButton.className = 'btn btn-sm btn-outline-danger mt-2';
        retryButton.onclick = () => {
          // Re-submit the same message
          userInputArea.value = messageContent;
          // Remove the error message
          chatBox.removeChild(errorMessage);
          // Remove the user message to prevent duplicates
          chatBox.removeChild(userMessageDiv);
          // Submit the form again
          chatForm.dispatchEvent(new Event('submit'));
        };
        errorMessage.appendChild(retryButton);
        
        // Replace the existing assistant message with our error message
        chatBox.replaceChild(errorMessage, assistantMessage);
      } finally {
        // Hide loading animation
        loadingDots.classList.remove('active');
        chatBox.scrollTop = chatBox.scrollHeight;
        // Update token usage
        if (window.fileTreeViewer) {
          window.fileTreeViewer.updateTokenDisplay();
        }
      }
    });
  }

  // Reset chat
  const resetChatBtn = document.getElementById('reset-chat');
  if (resetChatBtn) {
    resetChatBtn.addEventListener('click', () => {
      if (!confirm('Are you sure you want to reset the conversation?')) return;
      chatBox.innerHTML = '';
      loadingDots.classList.remove('active');
      fetch('/reset_conversation', { method: 'POST' })
        .catch((error) => console.error('Error resetting conversation:', error));
    });
  }

  // Auto-save settings on changes
  const anthropicApiKey = document.getElementById('anthropic_api_key');
  const openaiApiKey = document.getElementById('openai_api_key');
  const togetherApiKey = document.getElementById('together_api_key');

  [anthropicApiKey, openaiApiKey, togetherApiKey]
    .forEach(el => el && el.addEventListener('change', autoSaveSettings));

  // Add event listeners for token updates
  [userInputArea, systemMessageEl].forEach(el => {
    if (el) {
      el.addEventListener('input', debounceTokenUpdate);
    }
  });

  [selectedModelEl, outputLengthEl].forEach(el => {
    if (el) {
      el.addEventListener('change', updateTokenDisplay);
    }
  });

  // Debounce function for token updates
  function debounceTokenUpdate() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(updateTokenDisplay, 300);
  }

  // Debounce time for token updates (ms)
  const TOKEN_UPDATE_DEBOUNCE = 500;

  // Cache for token calculations
  const tokenCalculationCache = {
    lastInput: '',
    lastFiles: [],
    lastResult: null,
    clear() {
      this.lastInput = '';
      this.lastFiles = [];
      this.lastResult = null;
    }
  };

  // Function to update token display
  async function updateTokenDisplay() {
    try {
      const files = window.fileTreeViewer ? await window.fileTreeViewer.getSelectedFilesContent() : [];
      const userInput = document.getElementById('user-input')?.value || '';
      const modelName = document.getElementById('selected_model')?.value || '';
      const systemMessage = document.getElementById('system-message')?.value || '';
      const outputLength = parseInt(document.getElementById('output_length')?.value) || null;
      
      // Check cache before making request
      const cacheKey = JSON.stringify({
        input: userInput,
        files: files,
        model: modelName,
        system: systemMessage,
        output: outputLength
      });
      
      if (tokenCalculationCache.lastResult && 
          tokenCalculationCache.lastInput === cacheKey) {
        console.log('Using cached token calculation');
        if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
          window.updateTokenDisplays(tokenCalculationCache.lastResult);
        }
        return;
      }

      console.log('Calculating tokens for:', {
        modelName,
        userInput: userInput.length + ' chars',
        filesCount: files.length,
        systemMessage: systemMessage.length + ' chars'
      });

      const response = await fetch('/calculate_tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: modelName,
          conversation_history: getConversationHistory(),
          user_input: userInput,
          rag_context: files.join('\n'),
          system_message: systemMessage,
          output_length: outputLength
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      // Validate response data
      if (!data || typeof data !== 'object') {
        throw new Error('Invalid token calculation response');
      }

      // Update cache
      tokenCalculationCache.lastInput = cacheKey;
      tokenCalculationCache.lastResult = data;

      // Update display if ready
      if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
        console.log('Token display is ready, updating with data:', data);
        window.updateTokenDisplays(data);
      } else {
        console.log('Token display not ready, waiting for ready event...');
        const waitForDisplay = () => {
          window.updateTokenDisplays(data);
          window.removeEventListener('tokenDisplayReady', waitForDisplay);
        };
        window.addEventListener('tokenDisplayReady', waitForDisplay);
      }
    } catch (error) {
      console.error('Error updating token display:', error);
      const fallbackData = {
        error: error.message,
        component_tokens: {
          system: 0,
          history: 0,
          rag: 0,
          user_input: 0
        },
        total_tokens_with_output: 0,
        max_tokens: 8192,
        usage_ratio: 0,
        usage_color: 'danger',
        prompt_cost_per_1m: 0,
        completion_cost_per_1m: 0,
        total_tokens_used: 0,
        output_length: 0,
        cost_estimate: 0
      };
      
      if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
        window.updateTokenDisplays(fallbackData);
      }
    }
  }

  // Debounced version of updateTokenDisplay
  const debouncedUpdateTokenDisplay = debounce(updateTokenDisplay, TOKEN_UPDATE_DEBOUNCE);

  // Add event listeners for input changes
  document.addEventListener('DOMContentLoaded', function() {
    const userInput = document.getElementById('user-input');
    const fileTree = document.getElementById('file-tree');
    const systemMessage = document.getElementById('system-message');
    const selectedModel = document.getElementById('selected_model');
    const outputLength = document.getElementById('output_length');
    
    // Function to initialize token calculation
    const initTokenCalculation = () => {
      console.log('Initializing token calculation');
      
      // Initial token calculation
      updateTokenDisplay();
      
      // Calculate tokens when user types
      if (userInput) {
        userInput.addEventListener('input', () => {
          console.log('User input changed, updating tokens...');
          debouncedUpdateTokenDisplay();
        });
      }
      
      // Calculate tokens when files are selected
      if (fileTree) {
        fileTree.addEventListener('change', () => {
          console.log('File selection changed, updating tokens...');
          // Clear cache when files change
          tokenCalculationCache.clear();
          debouncedUpdateTokenDisplay();
        });
      }
      
      // Calculate tokens when system message changes
      if (systemMessage) {
        systemMessage.addEventListener('input', () => {
          console.log('System message changed, updating tokens...');
          debouncedUpdateTokenDisplay();
        });
      }
      
      // Calculate tokens when model changes
      if (selectedModel) {
        selectedModel.addEventListener('change', () => {
          console.log('Model changed, updating tokens...');
          // Clear cache when model changes
          tokenCalculationCache.clear();
          debouncedUpdateTokenDisplay();
        });
      }
      
      // Calculate tokens when output length changes
      if (outputLength) {
        outputLength.addEventListener('change', () => {
          console.log('Output length changed, updating tokens...');
          debouncedUpdateTokenDisplay();
        });
      }
      
      // Listen for token data updates
      window.addEventListener('tokenDataUpdated', (event) => {
        console.log('Token data updated:', event.detail);
      });
    };

    // Check if token display is ready
    if (window.isTokenDisplayReady && window.isTokenDisplayReady()) {
      console.log('Token display already ready, initializing immediately');
      initTokenCalculation();
    } else {
      console.log('Waiting for token display to be ready');
      window.addEventListener('tokenDisplayReady', () => {
        console.log('Token display ready event received');
        initTokenCalculation();
      });
    }
  });

  toggleApiKeys();
  updateModelDisplay(selectedModelEl ? selectedModelEl.value : '');
  if (selectedModelEl) {
    selectedModelEl.addEventListener('change', async () => {
      toggleApiKeys();
      autoSaveSettings();
      await updateModelLimits();
      
      // Clear token calculation cache when model changes
      tokenCalculationCache.clear();
      
      // Immediately update token display with new model's pricing
      updateTokenDisplay();
    });
  }

  // Initial model limits + file tree
  updateModelLimits().catch(console.error);
  initFileTreeViewer();
});

/**
 * Copy text to clipboard
 */
function copyToClipboard(text) {
  navigator.clipboard.writeText(text)
    .then(() => alert('Response copied to clipboard!'))
    .catch(err => console.error('Could not copy text:', err));
}

/**
 * Auto-save settings
 */
function autoSaveSettings() {
  const form = document.getElementById('settings-form');
  if (!form) return;
  const formData = new FormData(form);

  fetch('/submit', {
    method: 'POST',
    body: formData
  })
    .then(r => r.json())
    .then(data => {
      console.log('Settings saved:', data);
      const modelValue = document.getElementById('selected_model').value;
      updateModelDisplay(modelValue);
    })
    .catch(error => {
      console.error('Error saving settings:', error);
      alert('Error saving settings: ' + error);
    });
}

/**
 * Save conversation
 */
function saveConversation() {
  fetch('/save_conversation', { method: 'POST' })
    .then(response => {
      if (!response.ok) {
        throw new Error('Failed to save conversation history.');
      }
      return response.blob();
    })
    .then(blob => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = 'conversation_history.txt';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
    })
    .catch(error => {
      console.error('Error:', error);
      alert(error.message);
    });
}

/**
 * Update the model name displayed
 */
function updateModelDisplay(modelValue) {
  const displayEl = document.getElementById('current-model-display');
  if (!displayEl) return;

  let displayName = 'Select Model';
  // Map model values to display names
  const modelNameMap = {
    'claude-3-7-sonnet-20250219': 'Claude 3.7 Sonnet',
    'claude-3-5-sonnet-20241022': 'Claude 3.5 Sonnet',
    'gpt-4o-latest': 'GPT-4o',
    'gpt-4o-mini': 'GPT-4o Mini',
    'gpt-4.1': 'GPT-4.1', // New
    'o1': 'o1',
    'o1-mini': 'o1 Mini',
    'o3': 'o3', // New
    'o3-mini-2025-01-31': 'o3-mini', // Was o4-mini
    'meta-llama/Llama-3.3-70B-Instruct-Turbo': 'Llama 3 70B Instruct',
    'deepseek-ai/DeepSeek-V3': 'DeepSeek V3',
    'deepseek-ai/DeepSeek-R1': 'DeepSeek R1'
  };

  displayName = modelNameMap[modelValue] || 'Select Model';
  displayEl.textContent = displayName;
}

/**
 * Toggle API key inputs
 */
function toggleApiKeys() {
  const model = document.getElementById('selected_model')?.value || '';
  const anthropicGroup = document.getElementById('anthropic_api_key_group');
  const openaiGroup = document.getElementById('openai_api_key_group');
  const togetherGroup = document.getElementById('together_api_key_group');

  if (!anthropicGroup || !openaiGroup || !togetherGroup) return;

  // Determine provider based on model name prefix/content
  let provider = 'unknown';
  const modelLower = model.toLowerCase();
  if (modelLower.startsWith('claude')) {
    provider = 'anthropic';
  } else if (modelLower.startsWith('gpt') || modelLower.startsWith('o1') || modelLower.startsWith('o3')) { // Added o3
    provider = 'openai';
  } else if (modelLower.includes('llama') || modelLower.includes('deepseek')) {
    provider = 'together';
  }

  // Show/hide based on provider
  anthropicGroup.classList.toggle('hidden', provider !== 'anthropic');
  openaiGroup.classList.toggle('hidden', provider !== 'openai');
  togetherGroup.classList.toggle('hidden', provider !== 'together');
}

/**
 * Dynamically update model limits
 */
async function updateModelLimits() {
  const modelName = document.getElementById('selected_model')?.value;
  const outputLengthInput = document.getElementById('output_length');
  const helpText = document.getElementById('output_length_help');
  if (!modelName || !outputLengthInput || !helpText) return;

  try {
    console.log(`Updating limits for model: ${modelName}`);
    // Call backend to get model specific info, including max output tokens
    const response = await fetch('/calculate_tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_name: modelName,
        // Send minimal data just to get config
        conversation_history: '',
        user_input: '',
        rag_context: '',
        system_message: '',
        output_length: null // Let backend determine default/max
      })
    });

    if (response.ok) {
      const data = await response.json();
      // Use max_output_tokens field from the backend response
      const maxOutput = data?.max_output_tokens || 8192;

      console.log(`Received max output for ${modelName}: ${maxOutput}`);

      outputLengthInput.max = maxOutput;
      // If current value exceeds new max, reset it (or set to max)
      if (parseInt(outputLengthInput.value, 10) > maxOutput) {
        outputLengthInput.value = maxOutput; // Set to new max
      } else if (!outputLengthInput.value || parseInt(outputLengthInput.value, 10) <= 0) {
          // If input is empty or invalid, set a reasonable default or the max
          outputLengthInput.value = Math.min(8192, maxOutput); // Default to 8k or max, whichever is smaller
      }

      helpText.textContent = `Maximum number of tokens in the AI's response (max ${maxOutput.toLocaleString()})`;
    } else {
        console.error(`Failed to get limits for ${modelName}: ${response.status}`);
         helpText.textContent = `Could not fetch limits for ${modelName}. Defaulting max to 8,192.`;
         outputLengthInput.max = 8192;
    }
  } catch (error) {
    console.error('Error updating model limits:', error);
    helpText.textContent = 'Error fetching model limits. Defaulting max to 8,192.';
    outputLengthInput.max = 8192;
  }
}

/**
 * Initialize file tree viewer
 */
function initFileTreeViewer() {
  const fileTreeContainer = document.getElementById('file-tree-container');
  const fileTreeDiv = document.getElementById('file-tree');
  if (!fileTreeContainer || !fileTreeDiv) return;

  // Show the file tree container
  fileTreeContainer.style.display = 'flex';

  class FileTreeViewer {
    constructor(container) {
      this.container = container;
      this.selectedFiles = new Set();
      this.fileContents = new Map();
      this.expandedFolders = new Set(['library_assistant']);
      this.loadFileTree();
      
      // Initial token update
      this.updateTokenDisplay();
    }

    async loadFileTree() {
      try {
        const response = await fetch('/get_file_tree');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (!data.fileTree) {
          throw new Error('No file tree data received');
        }
        this.renderFileTree(data.fileTree);
        
        // Add this: Select default files after tree is rendered
        setTimeout(() => this.selectDefaultFiles(data.fileTree), 500);
      } catch (error) {
        console.error('Error loading file tree:', error);
      }
    }

    // Add this new method to select default files
    async selectDefaultFiles(rootNode) {
      const defaultFiles = ['.cursorrules', 'Comprehensive Library Guide.md'];
      
      // Function to recursively search for files
      const findAndSelectFiles = async (node, currentPath = '') => {
        const nodePath = currentPath ? `${currentPath}/${node.name}` : node.name;
        
        if (node.type === 'file' && defaultFiles.includes(node.name)) {
          console.log(`Found default file to select: ${nodePath}`);
          
          // Find checkbox in DOM
          const fileItems = this.container.querySelectorAll('.file-item');
          for (const item of fileItems) {
            if (item.dataset.path === nodePath) {
              const checkbox = item.querySelector('input[type="checkbox"]');
              if (checkbox) {
                checkbox.checked = true;
                await this.handleFileSelect(nodePath, node.tokens || 0, true);
                console.log(`Selected default file: ${nodePath}`);
              }
              break;
            }
          }
        }
        
        // Recursively search children
        if (node.children) {
          for (const child of node.children) {
            await findAndSelectFiles(child, nodePath);
          }
        }
      };
      
      // Start recursive search from root
      if (rootNode) {
        await findAndSelectFiles(rootNode);
      }
    }

    renderFileTree(node) {
      this.container.innerHTML = '';
      this._renderNode(node, 0, this.container);
    }

    _renderNode(node, level, parentContainer) {
      const container = document.createElement('div');
      container.className = 'file-item';

      const item = document.createElement('div');
      item.className = 'd-flex align-items-center';
      item.style.paddingLeft = `${level * 20}px`;

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'form-check-input';
      checkbox.checked = this.selectedFiles.has(node.path);

      if (node.type === 'directory') {
        this._renderDirectory(node, level, container, item, checkbox);
      } else {
        this._renderFile(node, container, item, checkbox);
      }

      parentContainer.appendChild(container);
    }

    _renderDirectory(node, level, container, item, checkbox) {
      const toggleBtn = document.createElement('span');
      toggleBtn.className = 'folder-toggle';
      toggleBtn.textContent = this.expandedFolders.has(node.path) ? '▼' : '▶';

      const icon = document.createElement('span');
      icon.className = 'file-icon';
      icon.textContent = this.expandedFolders.has(node.path) ? '📂' : '📁';

      const name = document.createElement('span');
      name.textContent = node.name;

      item.appendChild(toggleBtn);
      item.appendChild(checkbox);
      item.appendChild(icon);
      item.appendChild(name);

      const childContainer = document.createElement('div');
      childContainer.className = 'file-children';
      childContainer.style.display = this.expandedFolders.has(node.path) ? 'block' : 'none';

      if (node.children) {
        node.children.forEach(child => {
          this._renderNode(child, level + 1, childContainer);
        });
      }

      const toggleDirectory = (e) => {
        e.stopPropagation();
        const isExpanded = this.expandedFolders.has(node.path);
        if (isExpanded) {
          this.expandedFolders.delete(node.path);
        } else {
          this.expandedFolders.add(node.path);
        }
        childContainer.style.display = isExpanded ? 'none' : 'block';
        toggleBtn.textContent = isExpanded ? '▶' : '▼';
        icon.textContent = isExpanded ? '📁' : '📂';
      };

      toggleBtn.onclick = toggleDirectory;
      icon.onclick = toggleDirectory;

      checkbox.onchange = (e) => {
        e.stopPropagation();
        const checkboxes = childContainer.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
          cb.checked = checkbox.checked;
          const fileItem = cb.closest('.file-item');
          if (fileItem?.dataset?.path) {
            this.handleFileSelect(fileItem.dataset.path, 0, checkbox.checked);
          }
        });
      };

      container.appendChild(item);
      container.appendChild(childContainer);
    }

    _renderFile(node, container, item, checkbox) {
      const icon = document.createElement('span');
      icon.className = 'file-icon';
      icon.textContent = '📄';

      const name = document.createElement('span');
      name.textContent = node.name;

      item.appendChild(checkbox);
      item.appendChild(icon);
      item.appendChild(name);

      container.appendChild(item);
      container.dataset.path = node.path;

      checkbox.onchange = (e) => {
        e.stopPropagation();
        this.handleFileSelect(node.path, node.tokens, checkbox.checked);
      };

      const viewFile = async (e) => {
        e.stopPropagation();
        try {
          const content = await this.getFileContent(node.path);
          if (content) {
            const userInput = document.getElementById('user-input');
            userInput.value = `Please help me with this file:\n\n${content}`;
            userInput.dispatchEvent(new Event('input'));
          }
        } catch (error) {
          console.error('Error viewing file:', error);
        }
      };

      icon.onclick = viewFile;
      name.onclick = viewFile;
    }

    async handleFileSelect(path, tokens, checked) {
      if (checked) {
        try {
          const content = await this.getFileContent(path);
          if (content) {
            this.selectedFiles.add(path);
            this.fileContents.set(path, content);
          }
        } catch (error) {
          console.error('Error loading file:', error);
        }
      } else {
        this.selectedFiles.delete(path);
        this.fileContents.delete(path);
      }
      this.updateTokenDisplay();
    }

    async getFileContent(path) {
      if (this.fileContents.has(path)) {
        return this.fileContents.get(path);
      }
      const response = await fetch(`/get_file_content?path=${encodeURIComponent(path)}`);
      if (!response.ok) throw new Error('Failed to fetch file content');
      const data = await response.json();
      return data.content;
    }

    async updateTokenDisplay() {
      try {
        // Get the current user input (or default to an empty string)
        const userInput = document.getElementById('user-input')?.value || '';

        // Get content from selected files (using your existing method)
        const selectedFiles = await this.getSelectedFilesContent();

        // Call the token calculation function with the current inputs
        const tokenData = await calculateTokens(userInput, selectedFiles);

        // Update the token display component with the new data
        if (typeof window.updateTokenDisplays === 'function') {
          console.log('Calling updateTokenDisplays with data:', tokenData);
          window.updateTokenDisplays(tokenData);
        }
      } catch (error) {
        console.error('Error updating token display from FileTreeViewer:', error);
      }
    }

    async getSelectedFilesContent() {
      const contents = [];
      for (const path of this.selectedFiles) {
        try {
          const content = await this.getFileContent(path);
          if (content) {
            contents.push(content);
          }
        } catch (error) {
          console.error(`Error getting content for ${path}:`, error);
        }
      }
      return contents;
    }
  }

  // Initialize file tree viewer
  window.fileTreeViewer = new FileTreeViewer(fileTreeDiv);
}

/**
 * Retrieve conversation history from the chat-box
 */
function getConversationHistory() {
  const chatBox = document.getElementById('chat-box');
  if (!chatBox) return '';
  const messages = [];
  for (const messageDiv of chatBox.children) {
    const role = messageDiv.classList.contains('user')
      ? 'user'
      : messageDiv.classList.contains('assistant')
      ? 'assistant'
      : 'unknown';
    const content = messageDiv.textContent.replace(/^(User|Assistant): /, '');
    messages.push(`${role}: ${content}`);
  }
  return messages.join('\n');
}

// Token calculation and update functions
async function calculateTokens(userInput = '', selectedFiles = []) {
    console.log('Calculating tokens...', { userInput, selectedFiles });
    try {
        const settings = await getSettings();
        console.log('Settings:', settings);
        
        const modelName = settings.selected_model;
        const systemMessage = settings.system_message;
        
        // Get conversation history from chat box
        const chatBox = document.getElementById('chat-box');
        const conversationHistory = chatBox ? chatBox.innerText : '';
        console.log('Conversation history length:', conversationHistory.length);
        
        // Get RAG context from selected files
        const ragContext = selectedFiles.join('\n');
        console.log('RAG context length:', ragContext.length);
        
        console.log('Sending token calculation request...');
        const response = await fetch('/calculate_tokens', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model_name: modelName,
                conversation_history: conversationHistory,
                user_input: userInput,
                rag_context: ragContext,
                system_message: systemMessage,
                selected_files: selectedFiles,
                output_length: 8192 // Default max tokens
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log('Token calculation response:', data);
        
        // Ensure we have a valid data object
        if (!data || typeof data !== 'object') {
            throw new Error('Invalid token calculation response');
        }
        
        // Update the token display component
        if (typeof window.updateTokenDisplays === 'function') {
            console.log('Calling updateTokenDisplays with data:', data);
            window.updateTokenDisplays(data);
        }
        return data;
    } catch (error) {
        console.error('Error calculating tokens:', error);
        const fallbackData = {
            error: error.message,
            component_tokens: {
                system: 0,
                history: 0,
                rag: 0,
                user_input: 0
            },
            total_tokens_with_output: 0,
            max_tokens: 8192,
            usage_ratio: 0,
            usage_color: 'danger',
            prompt_cost_per_1m: 0,
            completion_cost_per_1m: 0,
            total_tokens_used: 0,
            output_length: 0,
            cost_estimate: 0
        };
        if (typeof window.updateTokenDisplays === 'function') {
            console.log('Calling updateTokenDisplays with fallback data:', fallbackData);
            window.updateTokenDisplays(fallbackData);
        }
        return fallbackData;
    }
}

// Function to get current settings
async function getSettings() {
    const selectedModel = document.getElementById('selected_model')?.value;
    const systemMessage = document.getElementById('system-message')?.value;
    return {
        selected_model: selectedModel || 'claude-3-5-sonnet-20240620',
        system_message: systemMessage || 'You are a helpful AI assistant.'
    };
}

// Debounce function to limit API calls
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Function to get selected files
function getSelectedFiles() {
    const checkboxes = document.querySelectorAll('.file-checkbox:checked');
    return Array.from(checkboxes)
        .filter(cb => cb.dataset.type === 'file')
        .map(cb => cb.dataset.path);
}
