Library Assistant: AI-Powered Tool for Managing and Querying Library Content

[Library Assistan is available as a Standalone Windows Executable](https://github.com/gpt-cmdr/ras-commander/blob/30bab76f376a260a24f7e61668242197a685b3f5/ai_tools/library_assistant/assistant.exe)
Just provide the API keys for your preferred provider and go!


Project Structure:
library_assistant/
├── api/
│   ├── anthropic.py
│   ├── logging.py
│   ├── openai.py
│   └── together.py
├── config/
│   └── config.py
├── database/
│   └── models.py
├── utils/
│   ├── file_handling.py
│   ├── cost_estimation.py
│   ├── conversation.py
│   └── context_processing.py
├── web/
│   ├── routes.py
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── styles.css
│       ├── fileTree.js
│       ├── main.js
│       └── tokenDisplay.js
└── assistant.py

Program Features:
1. Integration with Anthropic and OpenAI APIs for AI-powered responses
2. Context-aware processing using full context or RAG (Retrieval-Augmented Generation) modes
3. Dynamic file handling and content processing
4. Cost estimation for API calls
5. Conversation management and history saving
6. Web-based user interface using FastAPI
7. **Separated front-end code** in `index.html` by moving all JavaScript into dedicated static files:
   - `main.js` for vanilla JS, form handling, SSE logic
   - `tokenDisplay.js` (with `type="text/babel"`) for React/JSX token usage components
8. Customizable settings for model selection, context mode, and file handling
9. Error handling and user guidance

General Coding Rules and Guidelines:
1. Follow PEP 8 style guidelines for Python code
2. Use type hints and docstrings for improved code readability
3. Implement proper error handling and logging
4. Maintain separation of concerns between modules
5. Use asynchronous programming where appropriate for improved performance
6. Implement unit tests for critical functions
7. Keep sensitive information (e.g., API keys) secure and out of version control
8. Use meaningful variable and function names
9. Optimize for readability and maintainability
10. **Separate large inline scripts from HTML** into external `.js` or `.jsx` files (as shown with `main.js` and `tokenDisplay.js`)
11. Regularly update dependencies and address security vulnerabilities

The Library Assistant operates by:
1. Processing user queries through a web interface
2. Preparing context based on the selected mode (full context or RAG)
3. Sending prepared prompts to the chosen AI model (Anthropic, OpenAI, or Together)
4. Streaming and processing AI responses
5. Estimating and displaying costs for API calls
6. Managing conversation history and allowing for conversation saving
7. Providing user guidance and error handling as needed

The AI assistant interacting with the Library Assistant is a helpful expert with experience in:
- Python programming
- FastAPI web framework
- SQLAlchemy ORM
- Anthropic, OpenAI, and Together.ai APIs
- Natural Language Processing (NLP) techniques
- Retrieval-Augmented Generation (RAG)
- Asynchronous programming
- RESTful API design
- Database management
- Cost optimization for API usage
- Web development (HTML, CSS, JavaScript, React)
- Git version control

The assistant should provide accurate, context-aware, and helpful responses while adhering to the Library Assistant's capabilities and limitations. It should offer guidance on effective use of the tool, including query formulation and settings management, while maintaining a professional and knowledgeable persona throughout all interactions.
```

This revised `.cursorrules` explicitly references the new `main.js` and `tokenDisplay.js` files under `web/static/` and includes a guideline about separating inline scripts from HTML.

---

# 2. **Relevant Updated Sections of `Library_Assistant_README.md`**

Below is the **entire** `Library_Assistant_REAME.md` with the **Project Structure** section updated to show the new JavaScript files in `web/static/`. No content is omitted or elided.

```markdown
# Library Assistant

Library Assistant is an AI-powered tool for managing and querying library content, leveraging both Anthropic's Claude and OpenAI's GPT models. It provides a web interface for interacting with AI models while maintaining context awareness of your codebase or documentation.

## Features

- **Dual AI Provider Support**: Integration with both Anthropic (Claude) and OpenAI (GPT) models
- **Context-Aware Processing**: Two modes of operation:
  - Full Context: Uses complete codebase/documentation context
  - RAG (Retrieval-Augmented Generation): Dynamically retrieves relevant context
- **Web Interface**: Clean, intuitive web UI built with FastAPI and Bootstrap
- **Real-Time Cost Estimation**: Estimates API costs for each interaction
- **Conversation Management**: Save and export chat histories
- **Customizable Settings**: Configure API keys, models, and context handling
- **File Processing**:
  - Intelligent handling of Python and Markdown files
  - Configurable file/folder exclusions
  - Code stripping options for reduced token usage
- **Separated JavaScript**:
  - Inline scripts previously in `index.html` are now split into `main.js` (vanilla JS) and `tokenDisplay.js` (React/JSX for token usage), placed in `web/static/` for a cleaner architecture

## Installation

1. Clone the repository:
    ```bash
    # Start of Selection
    git clone https://github.com/gpt-cmdr/ras-commander.git
    # End of Selection
    cd library-assistant
    ```
2. Install dependencies:
    ```bash
    pip install fastapi uvicorn sqlalchemy jinja2 pandas anthropic openai tiktoken astor markdown python-multipart requests python-dotenv together
    ```
3. Set up your environment:
   - Obtain API keys from [Anthropic](https://www.anthropic.com/) and/or [OpenAI](https://openai.com/)
   - Configure your settings through the web interface

## Usage

1. Start the application:
    ```bash
    python assistant.py
    ```
2. Open your web browser to `http://127.0.0.1:8000`
3. Configure your settings:
   - Select your preferred AI model
   - Enter your API key(s)
   - Choose context handling mode
   - Adjust RAG parameters if using RAG mode
4. Start chatting with the AI assistant about your codebase or documentation

## Configuration

### Available Models

- **Anthropic**:
  - Claude 3.5 Sonnet

- **OpenAI**:
  - GPT-4o
  - GPT-4o-mini
  - o1-mini

### Context Modes

1. **Full Context**:
   - Provides complete codebase context to the AI
   - Best for smaller codebases
   - Higher token usage

2. **RAG Mode**:
   - Dynamically retrieves relevant context
   - More efficient for large codebases
   - Configurable chunk sizes

### File Processing Options

Configure exclusions in settings:

```python
omit_folders = [
    "__pycache__",
    ".git",
    "venv",
    # Add custom folders
]

omit_extensions = [
    ".jpg", ".png", ".pdf",
    # Add custom extensions
]

omit_files = [
    "specific_file.txt",
    # Add specific files
]
```

## Project Structure

The Library Assistant is organized into several key components, each with specific responsibilities:

```
library_assistant/
├── api/
│   ├── anthropic.py         # Anthropic API integration
│   ├── logging.py           # Centralized logging configuration
│   ├── openai.py            # OpenAI API integration
│   └── together.py          # Together.ai integration
├── config/
│   └── config.py            # Configuration management (database + environment)
├── database/
│   └── models.py            # SQLAlchemy database models
├── utils/
│   ├── file_handling.py     # File processing utilities
│   ├── cost_estimation.py   # API cost calculations
│   ├── conversation.py      # Chat history management
│   └── context_processing.py# Context handling (Full/RAG)
├── web/
│   ├── routes.py            # FastAPI route definitions
│   ├── templates/           # Jinja2 HTML templates (includes index.html)
│   └── static/              # All static assets
│       ├── styles.css
│       ├── fileTree.js
│       ├── main.js          # Primary vanilla JS logic, SSE streaming, form handling
│       └── tokenDisplay.js  # React/JSX (type="text/babel") for token usage display
└── assistant.py             # Main application entry point

### Component Breakdown

#### `api/`
Handles interactions with AI providers:
- **`anthropic.py`**: Manages Claude model interactions
- **`openai.py`**: Handles GPT model communications
- **`together.py`**: Simple integration for Together.ai
- **`logging.py`**: Centralized logging configuration for the entire app

#### `config/`
Contains configuration management:
- **`config.py`**: Manages settings, API keys, and runtime configurations in a database

#### `database/`
Manages data persistence:
- **`models.py`**: SQLAlchemy models for conversation history and settings

#### `utils/`
Core utility functions:
- **`file_handling.py`**: Processes and manages file operations
- **`cost_estimation.py`**: Calculates API usage costs and holds LLM Model information
- **`conversation.py`**: Handles chat history and exports
- **`context_processing.py`**: Manages context modes (Full or RAG)

#### `web/`
Web interface components:
- **`routes.py`**: FastAPI route definitions
- **`templates/`**: Jinja2 HTML templates (e.g., `index.html`)
- **`static/`**: CSS, JavaScript, and other static assets (including `main.js` and `tokenDisplay.js`)

#### Root Files
- **`assistant.py`**: Application entry point
- **`requirements.txt`**: Project dependencies
- **`README.md`**: Project documentation
- **`.env`**: Environment variables (not tracked in git)

## Error Handling

The application includes comprehensive error handling:
- API errors
- File processing errors
- Invalid settings
- Connection issues

Errors are logged and displayed in the web interface with appropriate messages.

## Development

### Adding New Features

1. Follow the existing project structure
2. Implement proper error handling
3. Update the web interface as needed
4. Document new features
5. Place any new JavaScript in `web/static/`, separating React/JSX from purely vanilla JS

### Code Style

- Follow PEP 8 guidelines
- Include docstrings for all functions
- Use type hints where appropriate
- Keep functions focused and modular
- Prefer external `.js` or `.jsx` files instead of large inline `<script>` blocks

## Performance Considerations

- RAG mode is recommended for large codebases
- Adjust chunk sizes based on your needs
- Consider token limits of your chosen model
- Monitor API costs through the interface

## Limitations

- Maximum context window varies by model
- API rate limits apply
- Token costs vary by provider and model
- Some file types are excluded by default

## Support

For issues, questions, or contributions:
1. Check the existing documentation
2. Review the codebase for similar functionality
3. Open an issue for bugs or feature requests
4. Submit pull requests with improvements

## License

This project is licensed under the MIT License - see the LICENSE file for details.
