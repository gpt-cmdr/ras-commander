// FileTreeViewer Component
class FileTreeViewer {
    constructor(container) {
        this.container = container;
        this.selectedFiles = new Set();
        this.expandedFolders = new Set(['library_assistant/']);
        this.searchQuery = '';
        this.sortOption = 'name-asc';
        this.hiddenTypes = new Set(['__pycache__']);
        this.fileContents = new Map();
        this.onSelectionChange = null;
    initialize(data) {
        this.fileData = null;
        this.container.innerHTML = '';
        this.fileData = data;
        if (data) {
        this.fileData = null;
            const rootElement = this.renderNode(data);
            this.container.appendChild(rootElement);
            
            // Auto-select default files after rendering
            this.autoSelectDefaultFiles();
        }
    }

    async autoSelectDefaultFiles() {
        // Expand all folders initially to ensure we can find the files
        const collectFolderPaths = (node, path = '') => {
            if (node.type === 'directory' && node.children) {
                const fullPath = path ? `${path}/${node.name}` : node.name;
                this.expandedFolders.add(fullPath);
                node.children.forEach(child => {
                    collectFolderPaths(child, fullPath);
                });
            }
        };
        
        if (this.fileData) {
            collectFolderPaths(this.fileData);
        }

        // Re-render with expanded folders
        this.render();

        // Find and select default files
        for (const filename of this.defaultFiles) {
            const filePath = this.findFilePath(this.fileData, filename);
            if (filePath) {
                await this.toggleFileSelection(filePath, true);
            }
        }

        // Keep folders expanded to show default files
        this.render();
    }

    findFilePath(node, targetFilename, currentPath = '') {
        if (node.type === 'file' && node.name === targetFilename) {
            return currentPath ? `${currentPath}/${node.name}` : node.name;
        }
        if (node.children) {
            for (const child of node.children) {
                const childPath = currentPath ? `${currentPath}/${node.name}` : node.name;
                const result = this.findFilePath(child, targetFilename, childPath);
                if (result) return result;
            }
        }
        return null;
    }

    getFolderStats(obj) {
        const stats = {
            totalTokens: 0,
            fileCount: 0,
            maxTokenFile: { name: '', tokens: 0 },
            minTokenFile: { name: '', tokens: Infinity },
            avgTokens: 0
        };

        const processNode = (node, path = '') => {
            Object.entries(node).forEach(([key, value]) => {
                const fullPath = path ? `${path}/${key}` : key;
                if (typeof value === 'number') {
                    stats.totalTokens += value;
                    stats.fileCount++;
                    if (value > stats.maxTokenFile.tokens) {
                        stats.maxTokenFile = { name: fullPath, tokens: value };
                    }
                    if (value < stats.minTokenFile.tokens) {
                        stats.minTokenFile = { name: fullPath, tokens: value };
                    }
                } else {
                    processNode(value, fullPath);
                }
            });
        };

        processNode(obj);
        stats.avgTokens = stats.fileCount > 0 ? Math.round(stats.totalTokens / stats.fileCount) : 0;
        return stats;
    }

    getSelectedStats() {
        const getNodeTokens = (obj, path) => {
            let total = 0;
            if (typeof obj === 'number') {
                return this.selectedFiles.has(path) ? obj : 0;
            }
            Object.entries(obj).forEach(([key, value]) => {
                const fullPath = path ? `${path}/${key}` : key;
                total += getNodeTokens(value, fullPath);
            });
            return total;
        };

        const selectedTokens = getNodeTokens(this.fileData, '');
        
        // Calculate costs for different models
        const costs = {
            claude: (selectedTokens / 1000000) * 3.00,  // $3.00 per million tokens
            gpt4: (selectedTokens / 1000000) * 10.00,   // $10.00 per million tokens
            gpt4mini: (selectedTokens / 1000000) * 0.60 // $0.60 per million tokens
        };

        return {
            totalTokens: selectedTokens,
            fileCount: this.selectedFiles.size,
            avgTokens: this.selectedFiles.size > 0 ? Math.round(selectedTokens / this.selectedFiles.size) : 0,
            costs: costs
        };
    }

    sortItems(items) {
        return Object.entries(items).sort(([keyA, valueA], [keyB, valueB]) => {
            const isFileA = typeof valueA === 'number';
            const isFileB = typeof valueB === 'number';
            
            if (isFileA !== isFileB) return isFileA ? 1 : -1;

            switch (this.sortOption) {
                case 'name-asc': return keyA.localeCompare(keyB);
                case 'name-desc': return keyB.localeCompare(keyA);
                case 'tokens-asc':
                    return (isFileA ? valueA : this.getFolderStats(valueA).totalTokens) 
                           - (isFileB ? valueB : this.getFolderStats(valueB).totalTokens);
                case 'tokens-desc':
                    return (isFileB ? valueB : this.getFolderStats(valueB).totalTokens)
                           - (isFileA ? valueA : this.getFolderStats(valueA).totalTokens);
                default: return 0;
            }
        });
    }

    renderToolbar() {
        return `
            <div class="mb-3">
                <div class="d-flex gap-2 mb-2">
                    <div class="flex-grow-1">
                        <input
                            type="text"
                            placeholder="Search files..."
                            value="${this.searchQuery}"
                            class="search-input form-control"
                        />
                    </div>
                    <select
                        class="sort-select form-select"
                        style="width: auto;"
                        value="${this.sortOption}"
                    >
                        <option value="name-asc">Name (A-Z)</option>
                        <option value="name-desc">Name (Z-A)</option>
                        <option value="tokens-asc">Tokens (Low to High)</option>
                        <option value="tokens-desc">Tokens (High to Low)</option>
                    </select>
                </div>
                <div class="d-flex gap-2">
                    <button class="expand-all btn btn-sm btn-outline-secondary">
                        Expand All
                    </button>
                    <button class="collapse-all btn btn-sm btn-outline-secondary">
                        Collapse All
                    </button>
                </div>
            </div>
        `;
    }

    renderTree(obj, path = '') {
        let html = '<div class="ml-4">';
        const sortedEntries = this.sortItems(obj);
        
        for (const [key, value] of sortedEntries) {
            const fullPath = path ? `${path}/${key}` : key;
            const isFolder = typeof value === 'object';
            
            if (this.hiddenTypes.has(key) && key !== '.cursorrules') continue;
            if (this.searchQuery && !fullPath.toLowerCase().includes(this.searchQuery.toLowerCase())) continue;
            
            if (isFolder) {
                const folderStats = this.getFolderStats(value);
                const isExpanded = this.expandedFolders.has(fullPath);
                
                html += `
                    <div class="folder" data-path="${fullPath}">
                        <div class="flex items-center py-1 hover:bg-gray-100">
                            <button class="toggle-folder mr-1">
                                ${isExpanded ? '▼' : '▶'}
                            </button>
                            <button class="select-folder mr-2">
                                □
                            </button>
                            📁
                            <span class="font-medium ml-2">${key}</span>
                            <span class="ml-2 text-sm text-gray-500">(${folderStats.totalTokens.toLocaleString()} tokens)</span>
                        </div>
                        ${isExpanded ? this.renderTree(value, fullPath) : ''}
                    </div>
                `;
            } else {
                const isSelected = this.selectedFiles.has(fullPath);
                const isDefaultFile = this.defaultFiles.includes(key);
                
                html += `
                    <div class="flex items-center py-1 hover:bg-gray-100 ${isDefaultFile ? 'bg-gray-50' : ''}">
                        <div class="w-4 mr-1"></div>
                        <input
                            type="checkbox"
                            class="file-checkbox mr-2 ml-1"
                            data-path="${fullPath}"
                            ${isSelected ? 'checked' : ''}
                            ${isDefaultFile ? 'data-default="true"' : ''}
                        />
                        <span class="file-icon">📄</span>
                        <span class="ml-2 ${isDefaultFile ? 'font-medium' : ''}">${key}</span>
                        <span class="ml-2 text-sm text-gray-500">(${value.toLocaleString()} tokens)</span>
                    </div>
                `;
            }
        }
        return html + '</div>';
    }

    renderStats() {
        const stats = this.getFolderStats(this.fileData);
        const selectedStats = this.getSelectedStats();

        return `
            <div class="p-3 bg-gray-100 rounded border" style="position: sticky; bottom: 0;">
                <div class="mb-2 border-bottom pb-2">
                    <div class="d-flex justify-content-between">
                        <span>Selected Files:</span>
                        <strong>${selectedStats.fileCount} of ${stats.fileCount} files</strong>
                    </div>
                    <div class="d-flex justify-content-between">
                        <span>Selected Tokens:</span>
                        <strong>${selectedStats.totalTokens.toLocaleString()} of ${stats.totalTokens.toLocaleString()}</strong>
                    </div>
                </div>
                <div>
                    <div class="fw-bold mb-1">Estimated Context Costs:</div>
                    <div class="d-flex justify-content-between">
                        <span>Claude 3.5:</span>
                        <strong>$${selectedStats.costs.claude.toFixed(4)}</strong>
                    </div>
                    <div class="d-flex justify-content-between">
                        <span>GPT-4:</span>
                        <strong>$${selectedStats.costs.gpt4.toFixed(4)}</strong>
                    </div>
                    <div class="d-flex justify-content-between">
                        <span>GPT-4 Mini:</span>
                        <strong>$${selectedStats.costs.gpt4mini.toFixed(4)}</strong>
                    </div>
                </div>
            </div>
        `;
    }

    render() {
        this.container.innerHTML = `
            <div class="border rounded-lg p-4 bg-white">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-xl font-semibold">Project Files</h2>
                </div>
                ${this.renderToolbar()}
                <div class="border rounded p-4 bg-gray-50 mb-4" style="max-height: 60vh; overflow-y: auto;">
                    ${this.renderTree(this.fileData)}
                </div>
                ${this.renderStats()}
            </div>
        `;

        // Attach event listeners after rendering
        this.attachEventListeners();
    }

    attachEventListeners() {
        // File checkboxes
        this.container.querySelectorAll('.file-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', async (e) => {
                e.preventDefault();
                const path = e.target.dataset.path;
                await this.toggleFileSelection(path);
            });
        });

        // Folder expansion
        this.container.querySelectorAll('.toggle-folder').forEach(button => {
            button.addEventListener('click', (e) => {
                const folderDiv = e.target.closest('.folder');
                const path = folderDiv.dataset.path;
                if (this.expandedFolders.has(path)) {
                    this.expandedFolders.delete(path);
                } else {
                    this.expandedFolders.add(path);
                }
                this.render();
            });
        });

        // Search input
        this.container.querySelector('.search-input').addEventListener('input', (e) => {
            this.searchQuery = e.target.value;
            this.render();
        });

        // Sort select
        this.container.querySelector('.sort-select').addEventListener('change', (e) => {
            this.sortOption = e.target.value;
            this.render();
        });

        // Expand/Collapse all
        this.container.querySelector('.expand-all').addEventListener('click', () => {
            const collectFolderPaths = (obj, path = '') => {
                Object.entries(obj).forEach(([key, value]) => {
                    if (typeof value === 'object') {
                        const fullPath = path ? `${path}/${key}` : key;
                        this.expandedFolders.add(fullPath);
                        collectFolderPaths(value, fullPath);
                    }
                });
            };
            collectFolderPaths(this.fileData);
            this.render();
        });

        this.container.querySelector('.collapse-all').addEventListener('click', () => {
            this.expandedFolders.clear();
            this.render();
        });
    }

    async getFileContent(path) {
        try {
            if (!path) return null;
            
            // Check if we already have the content cached
            if (this.fileContents.has(path)) {
                return this.fileContents.get(path);
            }

            const response = await fetch(`/get_file_content?path=${encodeURIComponent(path)}`);
            if (!response.ok) {
                throw new Error(`Failed to fetch file content: ${response.statusText}`);
            }
            
            const content = await response.json();
            // Cache the content
            this.fileContents.set(path, content);
            return content;
        } catch (error) {
            console.error('Error fetching file content:', error);
            return null;
        }
    }

    async toggleFileSelection(path, forceSelect = false) {
        if (!forceSelect && this.selectedFiles.has(path)) {
            this.selectedFiles.delete(path);
            this.updateAllCostDisplays();
            this.render();
        } else {
            const checkbox = this.container.querySelector(`[data-path="${path}"]`);
            if (checkbox) checkbox.disabled = true;

            const fileContent = await this.getFileContent(path);
            
            if (checkbox) checkbox.disabled = false;

            if (fileContent) {
                this.selectedFiles.add(path);
                this.updateAllCostDisplays();
                this.render();
            } else {
                console.error('Failed to load file content:', path);
                alert(`Failed to load content for ${path}`);
                return;
            }
        }

        if (this.onSelectionChange) {
            this.onSelectionChange(Array.from(this.selectedFiles));
        }
    }

    setSelectionChangeCallback(callback) {
        this.onSelectionChange = callback;
    }

    async getSelectedContents() {
        const contents = new Map();
        for (const path of this.selectedFiles) {
            const content = await this.getFileContent(path);
            if (content) {
                contents.set(path, content);
            }
        }
        return contents;
    }

    updateAllCostDisplays() {
        const stats = this.getSelectedStats();
        
        // Update file tree stats by re-rendering
        this.render();
        
        // Update total cost estimation for the message input area
        if (window.updateTotalCostEstimation) {
            window.updateTotalCostEstimation();
        }
    }
}