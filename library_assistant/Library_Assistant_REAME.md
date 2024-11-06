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

## Installation

1. Clone the repository:
```bash
# Start of Selection
git clone https://github.com/billk-FM/ras-commander.git
# End of Selection
cd library-assistant
```

2. Install dependencies:
```bash
pip install fastapi uvicorn sqlalchemy jinja2 pandas anthropic openai tiktoken astor markdown python-multipart requests python-dotenv
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

```
library_assistant/
├── api/
│   ├── anthropic.py    # Anthropic API integration
│   └── openai.py       # OpenAI API integration
├── config/
│   └── config.py       # Configuration management
├── database/
│   └── models.py       # Database models
├── utils/
│   ├── file_handling.py       # File processing utilities
│   ├── cost_estimation.py     # API cost calculations
│   ├── conversation.py        # Chat history management
│   └── context_processing.py  # Context handling
├── web/
│   ├── routes.py      # FastAPI routes
│   ├── templates/     # HTML templates
│   └── static/        # Static assets
└── assistant.py       # Main application entry point
```

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

### Code Style

- Follow PEP 8 guidelines
- Include docstrings for all functions
- Use type hints where appropriate
- Implement proper error handling
- Keep functions focused and modular

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