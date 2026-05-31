# Sanskrit Scripture RAG Assistant - Refactored Project

A production-grade **Retrieval-Augmented Generation (RAG)** system for querying Sanskrit scriptures using fine-tuned language models and semantic search.

## 🎯 Project Overview

This project has been restructured following industry best practices to ensure:

- **Maintainability**: Clear separation of concerns with modular architecture
- **Reliability**: Comprehensive error handling and graceful fallbacks
- **Testability**: Unit tests and integration test framework
- **Performance**: FAISS vector indexing, 4-bit quantization, efficient retrieval
- **Security**: Input validation, safe path handling, resource limits
- **Scalability**: Modular design for easy extensions and improvements

## 📁 Project Structure

```
sanskrity/
├── src/                           # Main source code
│   ├── __init__.py               # Package initialization
│   ├── config.py                 # Centralized configuration
│   ├── logger.py                 # Logging setup
│   ├── data_loader.py            # Data loading & processing
│   ├── models.py                 # Model initialization
│   ├── utils.py                  # Utility functions
│   ├── rag_chain.py              # RAG pipeline & vector store
│   ├── chat.py                   # Interactive chat interface
│   └── main.py                   # Application entry point
│
├── tests/                         # Unit tests
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_data_loader.py
│   └── test_utils.py
│
├── data/                          # Data files
│   ├── train.sn, train.en
│   ├── dev.sn, dev.en
│   ├── test.sn, test.en
│   └── *.json files
│
├── qwen/                          # Base Qwen model
├── qwen-finetuned/               # Fine-tuned Qwen with LoRA adapter
├── Shlokvaani/                   # Alternative model
├── res/                           # Resources (combined.csv, etc.)
├── sanskrit_faiss_index_itihasa/ # FAISS vector index
│
├── requirements.txt              # Python dependencies
├── .gitignore                    # Git ignore file
└── README.md                     # This file
```

## 🚀 Getting Started

### Installation

1. **Clone or download the project**

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables** (optional):
   ```bash
   export SANSKRIT_PROJECT_DIR=/path/to/sanskrity
   export CUDA_VISIBLE_DEVICES=0  # Specify GPU if needed
   ```

### Running the Application

**Start the interactive chat assistant**:
```bash
python src/server.py
```

This will:
1. Validate configuration and environment
2. Load Sanskrit scripture data
3. Initialize the FAISS vector store
4. Load the fine-tuned Qwen model
5. Start the server

## 📚 Module Documentation

### `config.py` - Configuration Management

Centralized configuration with environment variable support:

```python
from src.config import Config

# Access configuration
print(Config.MAX_TOKENS)
print(Config.EMBEDDINGS_MODEL)

# Validate configuration
if Config.validate():
    print("Configuration is valid")

# Get quantization config
bnb_config = Config.get_bnb_config()
```

**Key configurations**:
- Model paths and names
- Embedding model settings
- LLM parameters (tokens, temperature, etc.)
- Vector store settings
- Training parameters
- Resource allocation

### `logger.py` - Logging Setup

Structured logging with file and console output:

```python
from src.logger import get_logger

logger = get_logger(__name__)
logger.info("Information message")
logger.warning("Warning message")
logger.error("Error message")
```

### `data_loader.py` - Data Loading

Load and process Sanskrit scripture data:

```python
from src.data_loader import load_and_chunk_itihasa_data, get_document_summary

# Load data from CSV
docs = load_and_chunk_itihasa_data("data/combined.csv")

# Get summary statistics
summary = get_document_summary(docs)
print(f"Loaded {summary['total_documents']} documents")
```

### `models.py` - Model Initialization

Load and configure language models:

```python
from src.models import setup_local_llm, load_embedding_model

# Load LLM with adapter
llm = setup_local_llm(
    base_model_name="qwen",
    adapter_path="qwen-finetuned",
    use_adapter=True
)

# Load embedding model
embeddings = load_embedding_model("intfloat/multilingual-e5-large")
```

### `utils.py` - Utility Functions

Helper functions for common tasks:

```python
from src.utils import (
    devanagari_to_roman,
    check_cuda_availability,
    truncate_text,
    validate_query,
    clean_text
)

# Transliteration
roman = devanagari_to_roman("नमस्ते")  # 'namaste'

# Text validation
try:
    validate_query(user_input)
except ValueError as e:
    print(f"Invalid query: {e}")
```

### `rag_chain.py` - RAG Pipeline

Vector store and retrieval management:

```python
from src.rag_chain import (
    initialize_vector_store,
    create_qa_prompt,
    get_retriever,
    format_retrieved_documents
)

# Initialize vector store
vector_store = initialize_vector_store(documents)

# Create retriever
retriever = get_retriever(vector_store, k=5)

# Retrieve documents
docs = retriever.get_relevant_documents("What is dharma?")

# Format for display
context, citation = format_retrieved_documents(docs)
```

### `chat.py` - Chat Interface

Interactive user interface:

```python
from src.chat import chat_with_assistant

# Start interactive chat
exit_code = chat_with_assistant(llm, retriever, qa_prompt)
```

**Features**:
- Interactive query input
- Document retrieval and display
- LLM response generation
- Formatted output
- Error handling

### `main.py` - Application Entry Point

Orchestrates the full application flow:

```bash
python src/main.py
```
Allows to test quickly in a CLI Chat interface

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_config.py -v

# Run with coverage
pytest tests/ --cov=src -v
```

**Available test modules**:
- `test_config.py`: Configuration validation
- `test_data_loader.py`: Data loading and processing
- `test_utils.py`: Utility functions
- `test_rag_chain.py`: RAG pipeline (add as needed)

## 💾 Key Features

### 1. **Modular Architecture**

- **Single Responsibility**: Each module has one clear purpose
- **Loose Coupling**: Minimal dependencies between modules
- **High Cohesion**: Related functionality grouped together

### 2. **Error Handling**

Three-tier error handling strategy:
1. **Specific exceptions**: Handle known error types
2. **Graceful degradation**: Provide fallbacks
3. **User notification**: Clear error messages

Example:
```python
try:
    model = load_fine_tuned_model()
except FileNotFoundError:
    logger.warning("Fine-tuned model not found")
    model = load_base_model()  # Fallback
```

### 3. **Comprehensive Logging**

- File and console logging
- Multiple severity levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Structured formatting with timestamps

### 4. **Configuration Management**

- Centralized configuration in `config.py`
- Environment variable support
- Easy customization for different environments

### 5. **FAISS Vector Indexing**

- Semantic search using multilingual embeddings
- Index persistence (saved to disk)
- Efficient similarity search

### 6. **Model Quantization**

- 4-bit quantization for memory efficiency
- Reduced model size and latency
- Minimal quality loss

## 🔧 Configuration Tips

### Customize Model Settings

Edit `src/config.py`:

```python
class Config:
    BASE_MODEL = "qwen"  # or "mistral", etc.
    MAX_TOKENS = 512     # Max response length
    TEMPERATURE = 0.02   # Lower = more factual
    RETRIEVER_K = 5      # Number of documents to retrieve
```

### Adjust Logging Level

```python
from src.logger import setup_logger
import logging

logger = setup_logger(level=logging.DEBUG)
```

### Environment Variables

```bash
export SANSKRIT_PROJECT_DIR=/path/to/project
export CUDA_VISIBLE_DEVICES=0,1  # Multi-GPU
```

## 📊 Performance Optimization

### Already Implemented

- ✅ 4-bit quantization
- ✅ FAISS index persistence
- ✅ Efficient document retrieval
- ✅ Model merging (adapter + base)

### Potential Enhancements

- Batch query processing
- Response caching with LRU cache
- Query preprocessing
- Index partitioning for large datasets

## 🔐 Security Features

- **Input validation**: Query length and content checks
- **Path safety**: Prevent path traversal attacks
- **Resource limits**: Timeout and memory constraints
- **Error suppression**: No sensitive data in error messages

## 📝 Example Usage

### Interactive Chat

```bash
python src/main.py
```

### Programmatic Usage

```python
from src.config import Config
from src.data_loader import load_and_chunk_itihasa_data
from src.models import setup_local_llm
from src.rag_chain import initialize_vector_store, get_retriever, create_qa_prompt
from src.chat import process_query

# Initialize components
docs = load_and_chunk_itihasa_data(Config.DATA_PATH)
vector_store = initialize_vector_store(docs)
retriever = get_retriever(vector_store)
llm = setup_local_llm()
qa_prompt = create_qa_prompt()

# Process query
result = process_query(
    "What is dharma?",
    llm,
    retriever,
    qa_prompt
)

print(result)
```

## 🐛 Troubleshooting

### Issue: CUDA not available
**Solution**: Ensure PyTorch CUDA version matches your GPU drivers
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Issue: Out of memory
**Solution**: Reduce batch size or use CPU
```python
Config.USE_4BIT_QUANTIZATION = True  # Already enabled
Config.DEVICE_MAP = "cpu"  # Force CPU
```

### Issue: No documents retrieved
**Solution**: Check FAISS index and embedding model
```python
from src.rag_chain import get_document_statistics
stats = get_document_statistics(vector_store)
print(stats)
```

## 📚 Best Practices Applied

Following the SOLID principles and industry standards:

1. **Single Responsibility Principle**: Each function does one thing
2. **Open/Closed Principle**: Open for extension, closed for modification
3. **Liskov Substitution**: Proper inheritance and polymorphism
4. **Interface Segregation**: Minimal, focused interfaces
5. **Dependency Inversion**: Depend on abstractions, not implementations

## 🤝 Contributing

To maintain code quality:

1. Follow PEP 8 style guide
2. Add type hints to functions
3. Write docstrings for all public functions
4. Add unit tests for new features
5. Update documentation

## 📄 License

[Specify your license here]

## 📧 Contact

[Add contact information if needed]

---

**Version**: 1.0.0  
**Last Updated**: 2024  
**Maintainer**: Sanskrit RAG Team
