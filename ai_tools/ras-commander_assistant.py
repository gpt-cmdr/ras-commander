import os
import json
import uvicorn
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Text, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from pathlib import Path
import webbrowser
from datetime import datetime
import pandas as pd
import anthropic
from openai import OpenAI
import tiktoken
import astor
import ast
import re
import markdown

print("Initializing FastAPI")
app = FastAPI()

print("Setting up Jinja2 templates")
templates = Jinja2Templates(directory="templates")

print("Setting up SQLite with SQLAlchemy")
DATABASE_URL = "sqlite:///./settings.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define Settings model
class Settings(Base):
    __tablename__ = "settings"
    id = Column(String, primary_key=True, index=True, default="singleton")
    anthropic_api_key = Column(Text, nullable=True)
    openai_api_key = Column(Text, nullable=True)
    selected_model = Column(String, nullable=True)
    context_mode = Column(String, nullable=True)
    omit_folders = Column(Text, nullable=True)
    omit_extensions = Column(Text, nullable=True)
    omit_files = Column(Text, nullable=True)
    chunk_level = Column(String, nullable=True)
    initial_chunk_size = Column(Integer, default=32000)
    followup_chunk_size = Column(Integer, default=16000)

# Create the database tables
print("Creating the database tables")
Base.metadata.create_all(bind=engine)

# Define default settings
DEFAULT_SETTINGS = {
    "anthropic_api_key": "",
    "openai_api_key": "",
    "selected_model": "",
    "context_mode": "",
    "omit_folders": [
        "Bald Eagle Creek", 
        "__pycache__", 
        ".git", 
        ".github", 
        "tests", 
        "build", 
        "dist", 
        "ras_commander.egg-info", 
        "venv", 
        "example_projects", 
        "llm_summary", 
        "misc", 
        "future", 
        "ai_tools"
    ],
    "omit_extensions": [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.ico',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.zip', '.rar', '.7z', '.tar', '.gz',
        '.exe', '.dll', '.so', '.dylib',
        '.pyc', '.pyo', '.pyd',
        '.class',
        '.log', '.tmp', '.bak', '.swp',
        '.bat', '.sh',
    ],
    "omit_files": [
        'FunctionList.md',
        'DS_Store',
        'Thumbs.db',
        'llmsummarize',
        'example_projects.zip',
        '11_accessing_example_projects.ipynb',
        'Example_Projects_6_5.zip',
        'github_code_assistant.ipynb',
        'example_projects.ipynb',
        '11_Using_RasExamples.ipynb',
        'example_projects.csv',
        'rascommander_code_assistant.ipynb',
        'RasExamples.py'
    ],
    "chunk_level": "function",
    "initial_chunk_size": 32000,
    "followup_chunk_size": 16000
}

def load_settings():
    db = SessionLocal()
    settings = db.query(Settings).filter(Settings.id == "singleton").first()
    if not settings:
        # Initialize with default settings
        settings = Settings(
            id="singleton",
            **{key: json.dumps(value) if isinstance(value, list) else value 
               for key, value in DEFAULT_SETTINGS.items()}
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    db.close()
    return settings

# Update settings
def update_settings(data):
    db = SessionLocal()
    settings = db.query(Settings).filter(Settings.id == "singleton").first()
    for key, value in data.items():
        if key in ["omit_folders", "omit_extensions", "omit_files"]:
            setattr(settings, key, json.dumps(value))
        else:
            setattr(settings, key, value)
    db.commit()
    db.close()

# Function to read API keys from files (if needed)
def read_api_key(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"API key file not found: {file_path}")

# Initialize OpenAI client (only if OpenAI API key is provided)
def get_openai_client():
    settings = load_settings()
    if settings.openai_api_key:
        return OpenAI(api_key=settings.openai_api_key)
    return None

# Function to read system message from .cursorrules
def read_system_message():
    current_dir = Path.cwd()
    cursor_rules_path = current_dir.parent / '.cursorrules'

    if not cursor_rules_path.exists():
        raise FileNotFoundError("This script expects to be in a directory within the ras_commander repo which has a .cursorrules file in its parent directory.")

    with open(cursor_rules_path, 'r') as f:
        system_message = f.read().strip()

    if not system_message:
        raise ValueError("No system message found in .cursorrules file.")

    return system_message

# Function to set the context folder
def set_context_folder():
    current_dir = Path.cwd()
    return current_dir.parent

# Function to strip code from functions
def strip_code_from_functions(content):
    class FunctionStripper(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            new_node = ast.FunctionDef(
                name=node.name,
                args=node.args,
                body=[ast.Pass()],
                decorator_list=node.decorator_list,
                returns=node.returns
            )
            if (node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Str)):
                new_node.body = [node.body[0], ast.Pass()]
            return new_node

    try:
        tree = ast.parse(content)
        stripped_tree = FunctionStripper().visit(tree)
        return astor.to_source(stripped_tree)
    except SyntaxError:
        return content

# Function to handle Python files
def handle_python_file(content, filepath, strip_code, chunk_level='function'):
    header_end = content.find("class ") if "class " in content else len(content)
    header = content[:header_end]
    processed_content = f"\n\n----- {filepath.name} - header -----\n\n{header}\n\n----- End of header -----\n\n"
    
    if chunk_level == 'function':
        function_chunks = re.findall(r"(def .*?(?=\ndef |\Z))", content[header_end:], re.DOTALL)
        for chunk in function_chunks:
            if strip_code:
                chunk = strip_code_from_functions(chunk)
            processed_content += f"\n\n----- {filepath.name} - chunk -----\n\n{chunk}\n\n----- End of chunk -----\n\n"
    else:
        content = strip_code_from_functions(content[header_end:]) if strip_code else content[header_end:]
        processed_content += f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of full_file -----\n\n"
    
    return processed_content

# Function to handle Markdown files
def handle_markdown_file(content, filepath):
    if filepath.name in ["Comprehensive_Library_Guide.md", "STYLE_GUIDE.md"]:
        return f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of {filepath.name} -----\n\n"
    
    sections = re.split(r'\n#+ ', content)
    processed_content = ""
    for section in sections:
        processed_content += f"\n\n----- {filepath.name} - section -----\n\n# {section}\n\n----- End of section -----\n\n"
    return processed_content

# Function to combine files
def combine_files(summarize_subfolder, omit_folders, omit_extensions, omit_files, strip_code=False, chunk_level='function'):
    combined_text = ""
    file_token_counts = {}
    total_token_count = 0
    
    this_script = Path(__file__).name
    summarize_subfolder = Path(summarize_subfolder)
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")

    for filepath in summarize_subfolder.rglob('*'):
        if (filepath.name != this_script and 
            not any(omit_folder in filepath.parts for omit_folder in omit_folders) and
            filepath.suffix.lower() not in omit_extensions and
            not any(omit_file in filepath.name for omit_file in omit_files)):
            
            if filepath.is_file():
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                except UnicodeDecodeError:
                    with open(filepath, 'rb') as infile:
                        content = infile.read().decode('utf-8', errors='ignore')
                
                if filepath.suffix.lower() == '.py':
                    content = handle_python_file(content, filepath, strip_code, chunk_level)
                elif filepath.suffix.lower() == '.md':
                    content = handle_markdown_file(content, filepath)
                else:
                    content = f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of {filepath.name} -----\n\n"
                
                combined_text += content
                file_tokens = len(enc.encode(content))
                file_token_counts[str(filepath)] = file_tokens
                total_token_count += file_tokens

    return combined_text, total_token_count, file_token_counts

# Function to rank chunks (placeholder for actual ranking logic)
def rank_chunks(chunks):
    return chunks  # Implement your ranking algorithm here

# Function to chunk and rank combined text
def chunk_and_rank(combined_text, chunk_size):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    chunks = []
    current_chunk = ""
    current_file = ""
    
    for line in combined_text.split('\n'):
        if line.startswith("----- ") and line.endswith(" -----"):
            if current_chunk:
                chunks.append((current_file, current_chunk))
                current_chunk = ""
            current_file = line.strip("-").strip()
        else:
            current_chunk += line + "\n"
            if len(enc.encode(current_chunk)) > chunk_size:
                chunks.append((current_file, current_chunk))
                current_chunk = ""
    
    if current_chunk:
        chunks.append((current_file, current_chunk))
    
    ranked_chunks = rank_chunks(chunks)
    return ranked_chunks

# Function to estimate cost
def estimate_cost(input_tokens, output_tokens, pricing_df):
    input_cost = (input_tokens / 1e6) * pricing_df['Input ($/1M Tokens)'].iloc[0]
    output_cost = (output_tokens / 1e6) * pricing_df['Output ($/1M Tokens)'].iloc[0]
    return input_cost + output_cost

# Function to prepare context
def prepare_context(combined_text, mode='full_context', initial_chunk_size=32000, followup_chunk_size=16000):
    if mode == 'full_context':
        return combined_text
    elif mode == 'rag':
        ranked_chunks = chunk_and_rank(combined_text, initial_chunk_size)
        context = reconstruct_context(ranked_chunks, initial_chunk_size)
        return context
    else:
        raise ValueError("Invalid mode. Choose 'full_context' or 'rag'.")

def reconstruct_context(ranked_chunks, max_tokens):
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    context = "Retrieval system has provided these chunks which may be helpful to the query:\n\n"
    current_tokens = len(enc.encode(context))
    
    for file, chunk in ranked_chunks:
        chunk_tokens = len(enc.encode(chunk))
        if current_tokens + chunk_tokens > max_tokens:
            break
        context += f"{chunk}\n\n"
        current_tokens += chunk_tokens
    
    return context

# Initialize conversation history
print("Initializing conversation history")
conversation_history = []

def add_to_history(role, content):
    conversation_history.append({"role": role, "content": content})

def get_full_conversation():
    return "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in conversation_history])

def create_pricing_df(model):
    if model.startswith("claude"):
        provider = "anthropic"
        pricing_data = {
            "Model": ["Claude 3.5 Sonnet"],
            "Input ($/1M Tokens)": [3],
            "Output ($/1M Tokens)": [15],
            "Context Window (Tokens)": [200000],
            "Response Max Tokens": [8192]
        }
    elif model.startswith("gpt") or model.startswith("o1"):
        provider = "openai"
        if model == "gpt-4o-2024-08-06":
            pricing_data = {
                "Model": ["gpt-4o-2024-08-06"],
                "Input ($/1M Tokens)": [2.50],
                "Output ($/1M Tokens)": [10.00],
                "Context Window (Tokens)": [128000],
                "Response Max Tokens": [16000]
            }
        elif model == "gpt-4o-mini":
            pricing_data = {
                "Model": ["GPT-4o-mini"],
                "Input ($/1M Tokens)": [0.150],
                "Output ($/1M Tokens)": [0.600],
                "Context Window (Tokens)": [128000],
                "Response Max Tokens": [16000]
            }
        elif model == "o1-mini":
            pricing_data = {
                "Model": ["o1-mini"],
                "Input ($/1M Tokens)": [3.00],
                "Output ($/1M Tokens)": [12.00],
                "Context Window (Tokens)": [128000],
                "Response Max Tokens": [16000]
            }
        else:
            raise ValueError(f"Unsupported OpenAI model selected: {model}")
    else:
        raise ValueError(f"Unsupported model: {model}")
    
    pricing_df = pd.DataFrame(pricing_data)
    return {"pricing_df": pricing_df, "provider": provider}

# Function to send prompt and receive response for Anthropic
def anthropic_stream_response(client, prompt, max_tokens=8000):
    response_text = ""
    with client.messages.stream(
        max_tokens=max_tokens,
        messages=[
            {"role": "user", "content": prompt}
        ],
        model="claude-3-5-sonnet-20240620"
    ) as stream:
        for text in stream.text_stream:
            response_text += text
    return response_text

# Function to send prompt and receive response for OpenAI
def openai_stream_response(model, messages, max_tokens=16000):
    response_text = ""
    add_to_history("assistant", "")  # Placeholder

    try:
        openai_client = get_openai_client()
        if not openai_client:
            raise ValueError("OpenAI API key not provided.")
        
        response = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            stream=False
        )
        
        if response and response.choices:
            response_text = response.choices[0].message.content.strip()
        else:
            raise ValueError("No response or choices from OpenAI.")
    except Exception as e:
        raise e

    # Update conversation history
    conversation_history[-1]["content"] = response_text
    return response_text

# Function to stream response based on provider
def stream_response(provider, model, prompt, messages=None, max_tokens=None):
    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=load_settings().anthropic_api_key)
        client.model = model
        return anthropic_stream_response(client, prompt, max_tokens)
    elif provider == "openai":
        return openai_stream_response(model, messages, max_tokens)
    else:
        raise ValueError("Unsupported provider.")

# Function to handle combining and preparing context
def prepare_full_prompt(settings, user_query):
    # This function can now be simplified or even removed
    pass

# Global variables to store context
preprocessed_context = ""
preprocessed_rag_context = ""

def initialize_rag_context():
    print("Initializing RAG context")
    global preprocessed_context, preprocessed_rag_context
    settings = load_settings()
    selected_model = settings.selected_model
    context_mode = settings.context_mode
    omit_folders = json.loads(settings.omit_folders)
    omit_extensions = json.loads(settings.omit_extensions)
    omit_files = json.loads(settings.omit_files)
    chunk_level = settings.chunk_level
    initial_chunk_size = settings.initial_chunk_size
    followup_chunk_size = settings.followup_chunk_size

    print("Setting context folder")
    context_folder = set_context_folder()
    print("Combining files")
    combined_text, total_token_count, _ = combine_files(
        summarize_subfolder=context_folder, 
        omit_folders=omit_folders, 
        omit_extensions=omit_extensions, 
        omit_files=omit_files, 
        strip_code=True, 
        chunk_level=chunk_level
    )

    print("Reading system message")
    system_message = read_system_message()

    if context_mode == 'full_context':
        print("Setting full context")
        preprocessed_context = combined_text
    else:  # RAG mode
        print("Preparing RAG Chunks (takes 10-20 seconds)")
        preprocessed_rag_context = prepare_context(
            combined_text=combined_text, 
            mode='rag', 
            initial_chunk_size=initial_chunk_size, 
            followup_chunk_size=followup_chunk_size
        )

# Define conversation endpoint
@app.post("/chat")
async def chat(request: Request, message: dict):
    user_message = message.get("message")
    if not user_message:
        raise HTTPException(status_code=400, detail="No message provided.")
    
    try:
        # Add user message to history
        add_to_history("user", user_message)
        
        # Load settings
        settings = load_settings()
        selected_model = settings.selected_model
        context_mode = settings.context_mode
        
        # Prepare the full prompt using preprocessed context
        if context_mode == 'full_context':
            full_prompt = f"{read_system_message()}\n\nContext:\n{preprocessed_context}\n\nUser Query: {user_message}"
        else:  # RAG mode
            full_prompt = (
                f"{read_system_message()}\n\n<context>Context Chunks:\n{preprocessed_rag_context}\n\n</context>\n"
                "The context above is provided for your use in responding to the user's query:\n\n"
                f"User Query: {user_message}"
            )
        
        # Estimate cost
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        input_tokens = len(enc.encode(full_prompt)) if context_mode == 'full_context' else len(enc.encode(user_message)) + 32000
        output_tokens = 1000  # Assuming an average response length
        
        # Create pricing dataframe
        pricing_info = create_pricing_df(selected_model)
        pricing_df = pricing_info["pricing_df"]
        provider = pricing_info["provider"]
        
        estimated_cost = estimate_cost(input_tokens, output_tokens, pricing_df)

        # Communicate with the selected model
        if provider == "anthropic":
            anthropic_api_key = load_settings().anthropic_api_key
            client = anthropic.Anthropic(api_key=anthropic_api_key)
            max_tokens = int(pricing_df['Response Max Tokens'].iloc[0])
            assistant_response = anthropic_stream_response(client, full_prompt, max_tokens=max_tokens)
        elif provider == "openai":
            messages = [
                {"role": "system", "content": read_system_message()},
                {"role": "user", "content": full_prompt}
            ]
            assistant_response = openai_stream_response(selected_model, messages, max_tokens=16000)
        else:
            raise HTTPException(status_code=400, detail="Unsupported provider selected.")
        
        # Ensure the response is in markdown format
        assistant_response = markdown.markdown(assistant_response)
        
        # Return response
        return {"response": assistant_response, "estimated_cost": estimated_cost, "provider": provider}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# Define the homepage
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    settings = load_settings()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "settings": settings
    })

# Handle form submission (used for AJAX-based auto-saving)
@app.post("/submit", response_class=JSONResponse)
async def handle_submit(
    request: Request,
    anthropic_api_key: str = Form(None),
    openai_api_key: str = Form(None),
    selected_model: str = Form(None),
    context_mode: str = Form(None),
    initial_chunk_size: int = Form(None),
    followup_chunk_size: int = Form(None),
):
    updated_data = {}
    if anthropic_api_key is not None:
        updated_data["anthropic_api_key"] = anthropic_api_key
    if openai_api_key is not None:
        updated_data["openai_api_key"] = openai_api_key
    if selected_model is not None:
        updated_data["selected_model"] = selected_model
    if context_mode is not None:
        updated_data["context_mode"] = context_mode
    if initial_chunk_size is not None:
        updated_data["initial_chunk_size"] = initial_chunk_size
    if followup_chunk_size is not None:
        updated_data["followup_chunk_size"] = followup_chunk_size
    
    update_settings(updated_data)
    return {"status": "success"}

# Function to save conversation history to a file
def save_conversation():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"conversation_history_{timestamp}.txt"
    file_path = os.path.join(os.getcwd(), file_name)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        for message in conversation_history:
            f.write(f"{message['role'].capitalize()}: {message['content']}\n\n")
    
    return file_path

# Add endpoint to save conversation
@app.post("/save_conversation")
async def save_conversation_endpoint():
    try:
        file_path = save_conversation()
        return FileResponse(file_path, filename=os.path.basename(file_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save conversation: {str(e)}")

# Start the web browser automatically
def open_browser():
    webbrowser.open("http://127.0.0.1:8000")

# Function to run the FastAPI app and open browser
def run_app():
    uvicorn.run(app, host="127.0.0.1", port=8000)

# Global variables to store context
preprocessed_context = ""
preprocessed_rag_context = ""

def initialize_rag_context():
    global preprocessed_context, preprocessed_rag_context
    settings = load_settings()
    selected_model = settings.selected_model
    context_mode = settings.context_mode
    omit_folders = json.loads(settings.omit_folders)
    omit_extensions = json.loads(settings.omit_extensions)
    omit_files = json.loads(settings.omit_files)
    chunk_level = settings.chunk_level
    initial_chunk_size = settings.initial_chunk_size
    followup_chunk_size = settings.followup_chunk_size

    context_folder = set_context_folder()
    combined_text, total_token_count, _ = combine_files(
        summarize_subfolder=context_folder, 
        omit_folders=omit_folders, 
        omit_extensions=omit_extensions, 
        omit_files=omit_files, 
        strip_code=True, 
        chunk_level=chunk_level
    )

    system_message = read_system_message()

    if context_mode == 'full_context':
        preprocessed_context = combined_text
    else:  # RAG mode
        preprocessed_rag_context = prepare_context(
            combined_text=combined_text, 
            mode='rag', 
            initial_chunk_size=initial_chunk_size, 
            followup_chunk_size=followup_chunk_size
        )

# Main entry point
if __name__ == "__main__":
    templates_dir = Path("templates")
    if not templates_dir.exists():
        templates_dir.mkdir(parents=True, exist_ok=True)
    
    index_html_path = templates_dir / "index.html"
    if not index_html_path.exists():
        index_html = """
<!DOCTYPE html>
<html>
<head>
    <title>RAS-Commander AI Assistant Interface</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/4.3.0/marked.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }
        .container { max-width: 900px; margin: auto; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; }
        input, select, textarea { width: 100%; padding: 8px; box-sizing: border-box; }
        .chat-box { border: 1px solid #ced4da; padding: 10px; height: 400px; overflow-y: scroll; background-color: #ffffff; border-radius: 5px; }
        .message { margin: 10px 0; }
        .user { color: #0d6efd; }
        .assistant { color: #198754; }
        .error { color: red; }
        .btn { padding: 10px 20px; background-color: #0d6efd; color: white; border: none; cursor: pointer; border-radius: 5px; }
        .btn:hover { background-color: #0b5ed7; }
        .cost { margin-top: 10px; font-weight: bold; }
        .copy-btn {
            margin-left: 10px;
            padding: 5px 10px;
            background-color: #0d6efd;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 5px;
        }
        .copy-btn:hover {
            background-color: #0b5ed7;
        }
        .hidden { display: none; }
        /* Slider Styling */
        input[type=range] {
            -webkit-appearance: none;
            width: 100%;
            height: 10px;
            border-radius: 5px;
            background: #d3d3d3;
            outline: none;
            margin-top: 10px;
        }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #0d6efd;
            cursor: pointer;
            border: 2px solid #ffffff;
            box-shadow: 0 0 2px rgba(0,0,0,0.3);
        }
        input[type=range]::-moz-range-thumb {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #0d6efd;
            cursor: pointer;
            border: 2px solid #ffffff;
            box-shadow: 0 0 2px rgba(0,0,0,0.3);
        }
        input[type=range]::-webkit-slider-runnable-track {
            width: 100%;
            height: 10px;
            cursor: pointer;
            background: #d3d3d3;
            border-radius: 5px;
        }
        input[type=range]::-moz-range-track {
            width: 100%;
            height: 10px;
            cursor: pointer;
            background: #d3d3d3;
            border-radius: 5px;
        }
        /* Collapsible Settings */
        .settings-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }
        .settings-header h2 {
            margin: 0;
        }
        /* Save Conversation Button */
        .save-btn {
            padding: 10px 20px;
            background-color: #198754;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 5px;
        }
        .save-btn:hover {
            background-color: #146c43;
        }
        /* Responsive Layout for API Keys and Model Selection */
        @media (min-width: 768px) {
            .inline-form-group {
                display: flex;
                align-items: center;
            }
            .inline-form-group > div {
                flex: 1;
                margin-right: 10px;
            }
            .inline-form-group > div:last-child {
                margin-right: 0;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="settings-header mb-4" data-bs-toggle="collapse" data-bs-target="#settings-collapse" aria-expanded="false" aria-controls="settings-collapse">
            <h2>Settings</h2>
            <button class="btn btn-secondary">Show Settings</button> <!-- Changed label -->
        </div>
        <div class="collapse" id="settings-collapse">
            <form id="settings-form">
                <div class="form-group inline-form-group">
                    <div>
                        <label for="selected_model">Select Model:</label>
                        <select id="selected_model" name="selected_model" class="form-select" required>
                            <option value="" disabled>Select a model</option>
                            <option value="claude-3-5-sonnet-20240620" {% if settings.selected_model == 'claude-3-5-sonnet-20240620' %}selected{% endif %}>Claude 3.5 Sonnet (Anthropic)</option>
                            <option value="gpt-4o-2024-08-06" {% if settings.selected_model == 'gpt-4o-2024-08-06' %}selected{% endif %}>GPT-4o (OpenAI)</option>
                            <option value="gpt-4o-mini" {% if settings.selected_model == 'gpt-4o-mini' %}selected{% endif %}>GPT-4o-mini (OpenAI)</option>
                            <option value="o1-mini" {% if settings.selected_model == 'o1-mini' %}selected{% endif %}>o1-mini (OpenAI)</option>
                        </select>
                    </div>
                    <div id="anthropic_api_key_group" class="form-group hidden">
                        <label for="anthropic_api_key">Anthropic API Key:</label>
                        <input type="text" id="anthropic_api_key" name="anthropic_api_key" class="form-control" value="{{ settings.anthropic_api_key }}">
                    </div>
                    <div id="openai_api_key_group" class="form-group hidden">
                        <label for="openai_api_key">OpenAI API Key:</label>
                        <input type="text" id="openai_api_key" name="openai_api_key" class="form-control" value="{{ settings.openai_api_key }}">
                    </div>
                </div>

                <div class="form-group">
                    <label for="context_mode">Context Handling Mode:</label>
                    <select id="context_mode" name="context_mode" class="form-select" required>
                        <option value="" disabled>Select a mode</option>
                        <option value="full_context" {% if settings.context_mode == 'full_context' %}selected{% endif %}>Full Context</option>
                        <option value="rag" {% if settings.context_mode == 'rag' %}selected{% endif %}>Retrieval-Augmented Generation (RAG)</option>
                    </select>
                </div>

                <!-- RAG Sliders -->
                <div id="rag_sliders" class="hidden">
                    <div class="form-group">
                        <label for="initial_chunk_size">Initial RAG Context Size (tokens):</label>
                        <div class="d-flex align-items-center">
                            <input type="range" id="initial_chunk_size" name="initial_chunk_size" class="form-range flex-grow-1" min="16000" max="96000" step="1000" value="{{ settings.initial_chunk_size }}">
                            <span id="initial_chunk_size_value" class="ms-2">{{ settings.initial_chunk_size }}</span>
                        </div>
                    </div>
                    <div class="form-group mt-3">
                        <label for="followup_chunk_size">Follow-up RAG Context Size (tokens):</label>
                        <div class="d-flex align-items-center">
                            <input type="range" id="followup_chunk_size" name="followup_chunk_size" class="form-range flex-grow-1" min="16000" max="64000" step="1000" value="{{ settings.followup_chunk_size }}">
                            <span id="followup_chunk_size_value" class="ms-2">{{ settings.followup_chunk_size }}</span>
                        </div>
                    </div>
                </div>
            </form>
        </div>
        
        <h2 class="mt-5">Chat Interface</h2>
        <div class="chat-box" id="chat-box">
            <!-- Chat messages will appear here -->
        </div>
        <form id="chat-form" class="mt-3">
            <textarea id="user-input" class="form-control" placeholder="Enter your message here..." rows="7" required></textarea>
            <button type="submit" class="btn mt-2">Send</button>
        </form>
        <div class="cost" id="cost-display"></div>
        <button onclick="saveConversation()" class="save-btn mt-3">Save Conversation</button>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const selectedModel = document.getElementById('selected_model');
            const anthropicGroup = document.getElementById('anthropic_api_key_group');
            const openaiGroup = document.getElementById('openai_api_key_group');
            const contextMode = document.getElementById('context_mode');
            const ragSliders = document.getElementById('rag_sliders');
            const initialChunkSize = document.getElementById('initial_chunk_size');
            const initialChunkSizeValue = document.getElementById('initial_chunk_size_value');
            const followupChunkSize = document.getElementById('followup_chunk_size');
            const followupChunkSizeValue = document.getElementById('followup_chunk_size_value');

            // Function to toggle API key fields based on selected model
            function toggleApiKeys() {
                const model = selectedModel.value;
                if (model.startsWith('claude')) {
                    anthropicGroup.classList.remove('hidden');
                    openaiGroup.classList.add('hidden');
                } else if (model.startsWith('gpt') || model.startsWith('o1')) {
                    openaiGroup.classList.remove('hidden');
                    anthropicGroup.classList.add('hidden');
                } else {
                    anthropicGroup.classList.add('hidden');
                    openaiGroup.classList.add('hidden');
                }
            }

            // Function to toggle RAG sliders based on context mode
            function toggleRagSliders() {
                const mode = contextMode.value;
                if (mode === 'rag') {
                    ragSliders.classList.remove('hidden');
                } else {
                    ragSliders.classList.add('hidden');
                }
            }

            // Initial toggle based on current selection
            toggleApiKeys();
            toggleRagSliders();

            // Event listeners for changes
            selectedModel.addEventListener('change', () => {
                toggleApiKeys();
                autoSaveSettings();
            });

            contextMode.addEventListener('change', () => {
                toggleRagSliders();
                autoSaveSettings();
            });

            initialChunkSize.addEventListener('input', () => {
                initialChunkSizeValue.textContent = initialChunkSize.value;
                autoSaveSettings();
            });

            followupChunkSize.addEventListener('input', () => {
                followupChunkSizeValue.textContent = followupChunkSize.value; // Corrected variable name
                autoSaveSettings();
            });

            document.getElementById('anthropic_api_key').addEventListener('input', autoSaveSettings);
            document.getElementById('openai_api_key').addEventListener('input', autoSaveSettings);

            // Auto-save function
            function autoSaveSettings() {
                const formData = new FormData(document.getElementById('settings-form'));
                fetch('/submit', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    console.log('Settings saved:', data);
                })
                .catch(error => {
                    console.error('Error saving settings:', error);
                });
            }

            // Update initial and follow-up chunk size values on load and input
            initialChunkSize.addEventListener('input', () => {
                initialChunkSizeValue.textContent = initialChunkSize.value;
                autoSaveSettings();
            });

            followupChunkSize.addEventListener('input', () => {
                followupChunkSizeValue.textContent = followupChunkSize.value; // Corrected variable name
                autoSaveSettings();
            });

            // Initial update
            initialChunkSizeValue.textContent = initialChunkSize.value;
            followupChunkSizeValue.textContent = followupChunkSize.value;

            // Handle chat form submission
            const chatForm = document.getElementById('chat-form');
            const chatBox = document.getElementById('chat-box');
            const userInput = document.getElementById('user-input');
            const costDisplay = document.getElementById('cost-display');

            chatForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const message = userInput.value.trim();
                if (message === '') return;

                // Display user message
                const userMessage = document.createElement('div');
                userMessage.className = 'message user';
                userMessage.textContent = 'User: ' + message;
                chatBox.appendChild(userMessage);

                // Clear input
                userInput.value = '';

                // Show loading indicator
                const loadingMessage = document.createElement('div');
                loadingMessage.className = 'message assistant';
                loadingMessage.textContent = 'Assistant: Loading...';
                chatBox.appendChild(loadingMessage);

                // Scroll to bottom
                chatBox.scrollTop = chatBox.scrollHeight;

                try {
                    // Send message to backend
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ message: message })
                    });

                    // Remove loading indicator
                    chatBox.removeChild(loadingMessage);

                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail);
                    }

                    const data = await response.json();

                    // Display assistant response
                    const assistantMessage = document.createElement('div');
                    assistantMessage.className = 'message assistant';
                    assistantMessage.innerHTML = 'Assistant: ' + marked.parse(data.response);

                    // Add "Copy Response" button
                    const copyButton = document.createElement('button');
                    copyButton.textContent = 'Copy Response';
                    copyButton.className = 'copy-btn btn btn-sm';
                    copyButton.onclick = () => copyToClipboard(data.response);
                    assistantMessage.appendChild(copyButton);

                    chatBox.appendChild(assistantMessage);

                    // Scroll to bottom
                    chatBox.scrollTop = chatBox.scrollHeight;

                    // Update cost display
                    costDisplay.textContent = `Estimated Cost: $${data.estimated_cost.toFixed(6)} (${data.provider})`;

                } catch (error) {
                    console.error('Error:', error);
                    const errorMessage = document.createElement('div');
                    errorMessage.className = 'message assistant error';
                    errorMessage.textContent = 'Error: ' + error.message;
                    chatBox.appendChild(errorMessage);
                    chatBox.scrollTop = chatBox.scrollHeight;
                }
            });

            function copyToClipboard(text) {
                navigator.clipboard.writeText(text).then(() => {
                    alert('Response copied to clipboard!');
                }, (err) => {
                    console.error('Could not copy text: ', err);
                });
            }

            // Function to save conversation history
            window.saveConversation = function() {
                fetch('/save_conversation', {
                    method: 'POST'
                })
                .then(response => {
                    if (response.ok) {
                        return response.blob();
                    } else {
                        throw new Error('Failed to save conversation history.');
                    }
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
        });
    </script>
</body>
</html>
"""
        with open(index_html_path, "w", encoding="utf-8") as f:
            f.write(index_html)
    
    # Initialize RAG context at startup
    try:
        initialize_rag_context()
        print("RAG context initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize RAG context: {e}")
    
    # Open the browser
    open_browser()
    
    # Run the app
    run_app()
