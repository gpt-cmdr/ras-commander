# Repository Context Extraction Agent

An intelligent Claude subagent that extracts and optimizes repository context for Large Language Model consumption using tiktoken-based token counting and advanced content filtering.

## Overview

The Repository Context Extraction Agent analyzes code repositories and generates optimized context extracts that fit within LLM token budgets (default ~100k tokens). It intelligently filters out noise (images, large outputs, binary files) while preserving the most relevant documentation and code for LLM analysis.

## Features

### 🔍 **Intelligent Repository Analysis**
- Scans repository structure and identifies file types
- Analyzes content relevance with priority scoring
- Builds comprehensive file inventory with token counts
- Detects and filters binary files, images, and large outputs

### 🎯 **Token-Aware Processing**
- Uses tiktoken for precise token counting across different models
- Optimizes content selection to fit target context windows
- Provides detailed token analytics and budget management
- Supports multiple token budget targets (default 100k)

### 🧹 **Smart Content Filtering**
- Removes images and rich media from Jupyter notebooks
- Truncates large DataFrame outputs and visualizations
- Filters out build artifacts, dependencies, and generated files
- Preserves essential documentation and core implementation code

### 📊 **Flexible Output Formats**
- Combined docs and code in single file
- Separate documentation and code files
- Focus-specific extracts based on user requirements
- Structured output with clear file boundaries and metadata

## Installation

### Prerequisites
- Python 3.7 or higher
- `uv` package manager (recommended) or `pip`

### Install Dependencies

Using `uv` (recommended):
```bash
cd ai_tools/subagent/repository_context_agent
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

Using `pip`:
```bash
cd ai_tools/subagent/repository_context_agent
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Extract context from a repository with default settings
python agent.py --repo /path/to/repository

# Specify custom token budget
python agent.py --repo /path/to/repository --budget 150000

# Focus on specific areas
python agent.py --repo /path/to/repository --focus documentation api

# Generate separate docs and code files
python agent.py --repo /path/to/repository --separate

# Extract only documentation
python agent.py --repo /path/to/repository --output docs_only
```

### Advanced Usage

```bash
# Custom model for token counting
python agent.py --repo /path/to/repo --model gpt-4-turbo --budget 128000

# Specify output directory
python agent.py --repo /path/to/repo --output-dir ./extracts

# Multiple focus areas with code-only output
python agent.py --repo /path/to/repo --focus core api database --output code_only
```

### Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--repo` | Path to repository root (required) | - |
| `--budget` | Token budget for extraction | 100000 |
| `--model` | Model for token counting | gpt-4 |
| `--focus` | Focus areas (space-separated) | None |
| `--output` | Output format (combined/docs_only/code_only) | combined |
| `--separate` | Generate separate docs and code files | False |
| `--output-dir` | Output directory | ./output |

## Examples

### Example 1: Basic Repository Analysis
```bash
python agent.py --repo /home/user/my-project --budget 100000
```

Output:
- `my-project_context.txt` with optimized repository context

### Example 2: Documentation Focus
```bash
python agent.py --repo /home/user/my-project --focus documentation setup --output docs_only
```

Output:
- `my-project_context.txt` containing only documentation and setup files

### Example 3: Separate Files with API Focus
```bash
python agent.py --repo /home/user/api-server --focus api endpoints --separate
```

Output:
- `api-server_documentation.txt` - Documentation and configuration
- `api-server_code.txt` - Code implementations and examples

## Architecture

### Core Components

#### `agent.py`
Main agent orchestrator that:
- Handles command-line interface
- Coordinates repository analysis
- Manages content extraction and optimization
- Generates structured output files

#### `utils/token_counter.py`
Advanced token counting utility featuring:
- Multiple model support via tiktoken
- Content efficiency analysis
- Smart truncation strategies
- Token budget optimization

#### `utils/file_processor.py`
Intelligent file analysis system providing:
- Repository structure scanning
- File categorization and prioritization
- Binary file detection
- Focus area relevance scoring

#### `utils/notebook_cleaner.py`
Jupyter notebook preprocessing that:
- Removes images and visualizations
- Truncates large DataFrame outputs
- Cleans execution metadata
- Preserves code and markdown content

#### `utils/content_optimizer.py`
Advanced content selection engine with:
- Multi-pass file selection strategy
- Category-balanced allocation
- Efficiency-based optimization
- Smart content truncation

### File Categories

The agent categorizes files into:
- **Documentation**: `.md`, `.rst`, `.txt`, README files
- **Code**: `.py`, `.js`, `.java`, `.cpp`, `.c`, `.go`, etc.
- **Configuration**: `.json`, `.yaml`, `.toml`, `.ini` files
- **Notebooks**: `.ipynb` files with special processing
- **Web**: `.html`, `.css`, `.js` frontend files
- **Data**: `.csv`, `.json`, database files

### Priority System

Files are prioritized based on:
1. **File Type Priority**: README > core modules > configs > examples > tests
2. **Path Relevance**: `/src/`, `/lib/` paths get priority boosts
3. **Focus Area Matching**: Files matching specified focus areas
4. **Content Density**: Information-rich files prioritized
5. **Size Efficiency**: Balanced token-to-information ratio

## Configuration

### Focus Areas

Supported focus areas include:
- `documentation` - README files, docs, guides
- `api` - API definitions, endpoints, handlers
- `core` - Main modules, entry points
- `config` - Configuration and setup files
- `data` - Data models, schemas, migrations
- `test` - Test files and specifications
- `ui` - User interface components
- `util` - Utility functions and helpers

### Token Budgets

Recommended token budgets by model:
- **GPT-3.5-turbo**: 15,000 tokens
- **GPT-4**: 7,000 tokens  
- **GPT-4-turbo**: 120,000 tokens
- **Claude-3**: 180,000 tokens

## Output Format

### Combined Output Structure
```
# Repository Context Extract

## Analysis Summary
- Repository: /path/to/repo
- Total Files Found: 150
- Files Selected: 45
- Total Tokens: 98,234/100,000
- Focus Areas: documentation, api

## File Categories Selected
- Documentation: 12 files, 25,678 tokens
- Code: 28 files, 65,432 tokens
- Configuration: 5 files, 7,124 tokens

## Selected Files Structure
```
[file tree of included files]
```

## Repository Content
[processed file contents with clear boundaries]
```

### Separate Output Files

When using `--separate`:
- `{repo_name}_documentation.txt` - All documentation and configuration
- `{repo_name}_code.txt` - All code implementations

## Integration with Claude

This subagent is designed to work seamlessly with Claude Code environments:

1. **Import the agent** into your Claude subagent directory
2. **Use with `uv`** for Python environment management
3. **Direct filesystem access** for local repository analysis
4. **Optimized token usage** for Claude's context windows

### Claude Usage Example
```python
# In a Claude conversation
# Upload repository or specify local path
"Please use the repository context agent to analyze /path/to/my-repo 
with focus on API documentation and core modules, using a 150k token budget"
```

## Troubleshooting

### Common Issues

**Error: Repository path does not exist**
- Verify the repository path is correct
- Ensure you have read permissions

**Error: Token counting failed**
- Check tiktoken installation
- Verify model name is supported

**Warning: Budget exceeded**
- Reduce token budget or use content optimization
- Increase focus specificity to reduce scope

**Empty output**
- Check file filters and focus areas
- Verify repository contains supported file types

### Performance Tips

1. **Use specific focus areas** to reduce processing time
2. **Set appropriate token budgets** for your use case
3. **Exclude large directories** with build artifacts
4. **Use separate outputs** for large repositories

## Contributing

To extend the Repository Context Extraction Agent:

1. Add new file type processors in `utils/file_processor.py`
2. Enhance optimization strategies in `utils/content_optimizer.py`
3. Improve content cleaning in respective utility modules
4. Update tests and documentation

## License

This agent is part of the ras-commander project. See the main project license for details.