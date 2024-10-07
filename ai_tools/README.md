# RAS-Commander AI Assistant

RAS-Commander AI Assistant is a web-based interface built with FastAPI that leverages OpenAI and Anthropic APIs to provide an intelligent conversational agent. It offers customizable settings, cost estimation, and the ability to save conversation histories, making it a versatile tool for developers and AI enthusiasts.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Usage](#usage)
- [Saving Conversations](#saving-conversations)
- [License](#license)

## Features

- **Chat Interface**: Engage in conversations with the AI assistant through a user-friendly web interface.
- **API Integration**: Supports both OpenAI and Anthropic models for flexible AI responses.
- **Customizable Settings**: Configure models, context handling modes, and chunk sizes directly from the interface.
- **Cost Estimation**: Estimate the cost of each interaction based on token usage.
- **Conversation History**: Save and download your conversation history for future reference.
- **Context Management**: Combines and processes files from specified directories to provide context-aware responses.

## Installation

### Prerequisites

- **Python 3.8+**: Ensure you have Python installed. You can download it from [python.org](https://www.python.org/downloads/).
- **Git**: To clone the repository. Download from [git-scm.com](https://git-scm.com/downloads).

### Setup

1. **Download the Python File**

either git clone the repository or grab the 'ras-commander_assistant.py' file 

2. **Open an Anaconda Terminal and/or Activate Your Virtual Environment**

Everyone has their favorite method, I just open anaconda and get a terminal, or use VS Code. 

3. **Install Dependencies**

   ```bash
   pip install fastapi uvicorn sqlalchemy jinja2 pandas anthropic openai tiktoken astor markdown requests python-multipart
   ```
4. **Running the Application**

Execute the script using Python inside your virtual environment:

```bash
python ras-commander_assistant.py
```


Upon running, the application will:

- Create necessary directories and templates if they don't exist.
- Automatically open the web browser pointing to `http://127.0.0.1:8000`.
- Start the FastAPI server.

## Usage

1. **Access the Web Interface**

   Open your browser to `http://127.0.0.1:8000` if it doesn't open automatically.

2. **Configure Settings**

   - **Select Model**: Choose between supported OpenAI or Anthropic models.
   - **API Keys**: Enter the corresponding API key based on the selected model.
   - **Context Handling Mode**:
     - **Full Context**: Uses the entire combined text as context.
     - **Retrieval-Augmented Generation (RAG)**: Uses ranked chunks of context for responses.
   - **RAG Settings**: Adjust initial and follow-up chunk sizes if RAG mode is selected.

   *Settings are auto-saved upon changes.*

3. **Chat Interface**

   - **Send Message**: Enter your query in the text area and click "Send".
   - **View Responses**: The assistant's replies will appear in the chat box.
   - **Copy Response**: Use the "Copy Response" button to copy the assistant's reply to your clipboard.
   - **Cost Display**: View the estimated cost of the interaction below the chat box.

## Saving Conversations

To save your conversation history:

1. Click the "Save Conversation" button below the chat interface.
2. A `.txt` file containing your conversation will be downloaded automatically.

*The file is named with a timestamp, e.g., `conversation_history_20240427_153045.txt`.*

## License

This project is licensed under the [MIT License](LICENSE).

---

*For any issues or contributions, please contact [your.email@example.com](mailto:your.email@example.com).*
