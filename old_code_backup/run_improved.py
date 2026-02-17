"""
Sanskrit Scripture RAG (Retrieval-Augmented Generation) Assistant
================================================================================
Command-line application for querying Sanskrit scriptures using fine-tuned LLM
and FAISS vector store for semantic search.

Features:
- Local fine-tuned Qwen model with LoRA adapters
- FAISS-based semantic search over Sanskrit shlokas
- Automatic citation of source material (book, chapter, verse)
- Bidirectional Sanskrit-English content retrieval
- Graceful error handling with fallback models
- Structured logging for debugging and monitoring
"""

import os
import sys
import torch
import pandas as pd
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Configure logging for production-ready debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('sanskrit_rag.log')  # Also log to file
    ]
)
logger = logging.getLogger(__name__)

# LangChain and Hugging Face imports
from peft import PeftModel
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_community.llms import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig
from langchain_core.documents import Document

# Transliteration imports
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate


# ============================================================================
# CONFIGURATION - Centralized settings
# ============================================================================
class Config:
    """Configuration class for all paths and model parameters"""
    
    # Paths (make these configurable for different environments)
    PROJECT_DIR = os.environ.get('SANSKRIT_PROJECT_DIR', 'D:/sanskrity')
    DATA_PATH = os.path.join(PROJECT_DIR, "res/combined.csv")
    ADAPTER_PATH = os.path.join(PROJECT_DIR, "qwen-finetuned")
    BASE_MODEL = "qwen"
    FAISS_INDEX_PATH = os.path.join(PROJECT_DIR, "sanskrit_faiss_index_itihasa")
    LOG_FILE = "sanskrit_rag.log"
    
    # Embedding model
    EMBEDDINGS_MODEL = "intfloat/multilingual-e5-large"
    
    # Model parameters
    MAX_TOKENS = 512
    TEMPERATURE = 0.02  # Low for factual RAG
    TOP_P = 0.9
    RETRIEVER_K = 1  # Number of documents to retrieve
    
    # Quantization configuration
    @staticmethod
    def get_bnb_config() -> BitsAndBytesConfig:
        """Get BitsAndBytes quantization configuration"""
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16
        )
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration paths exist"""
        required_paths = [cls.PROJECT_DIR]
        for path in required_paths:
            if not os.path.exists(path):
                logger.error(f"Configuration error: Required path does not exist: {path}")
                return False
        return True


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_cuda_availability() -> None:
    """Check and log CUDA availability"""
    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        logger.info(f"✓ CUDA available. Device: {device_name}")
    else:
        logger.warning("⚠ CUDA not available. This script may run very slowly on CPU.")


def devanagari_to_roman(devanagari_text: str, output_scheme=sanscript.IAST) -> str:
    """
    Transliterate Devanagari text to Roman script.
    
    Args:
        devanagari_text: Text in Devanagari script
        output_scheme: Target transliteration scheme (default: IAST)
    
    Returns:
        Romanized text or error message
    """
    try:
        romanized = transliterate(devanagari_text, sanscript.DEVANAGARI, output_scheme)
        logger.debug(f"Transliterated {len(devanagari_text)} chars successfully")
        return romanized
    except Exception as e:
        logger.error(f"Transliteration failed: {e}")
        return f"Error during transliteration: {e}"


def load_and_chunk_itihasa_data(csv_path: str) -> List[Document]:
    """
    Load CSV data and create LangChain Documents.
    
    Args:
        csv_path: Path to CSV file containing shloka data
    
    Returns:
        List of LangChain Documents with metadata
    """
    try:
        if not os.path.exists(csv_path):
            logger.warning(f"CSV file not found at {csv_path}")
            return []
        
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded CSV with {len(df)} rows from {csv_path}")
        
        documents = []
        for index, row in df.iterrows():
            try:
                # Use Sanskrit text as primary content for embedding
                content = row.get('sn', '')
                
                # Store complete metadata for citations
                metadata = {
                    "book": row.get('book', 'Unknown'),
                    "chapter": row.get('chapter', 'Unknown'),
                    "shloka_num": row.get('shloka', 'Unknown'),
                    "english_text": row.get('en', 'Translation not available')
                }
                documents.append(Document(page_content=content, metadata=metadata))
            
            except Exception as e:
                logger.warning(f"Skipped row {index}: {e}")
                continue
        
        logger.info(f"Created {len(documents)} documents from CSV")
        return documents
    
    except Exception as e:
        logger.error(f"Critical error loading CSV: {e}")
        return []


# ============================================================================
# VECTOR STORE INITIALIZATION
# ============================================================================

def initialize_vector_store(
    chunk_docs: Optional[List[Document]] = None,
    embedding_model_name: str = Config.EMBEDDINGS_MODEL
) -> Optional[FAISS]:
    """
    Load or create FAISS vector store with HuggingFace embeddings.
    
    Args:
        chunk_docs: Optional list of documents to create new index from
        embedding_model_name: Name of HuggingFace embedding model
    
    Returns:
        FAISS vector store instance or None on failure
    """
    logger.info(f"Initializing vector store from: {Config.FAISS_INDEX_PATH}")
    
    try:
        # Initialize embedding model
        embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
        logger.info(f"Loaded embedding model: {embedding_model_name}")
        
        if os.path.exists(Config.FAISS_INDEX_PATH):
            logger.info("Loading existing FAISS index from disk")
            vector_store = FAISS.load_local(
                folder_path=Config.FAISS_INDEX_PATH,
                embeddings=embedding_model,
                allow_dangerous_deserialization=True
            )
            logger.info("✓ FAISS index loaded successfully")
        else:
            logger.info("FAISS index not found, creating new index...")
            if chunk_docs is None:
                chunk_docs = load_and_chunk_itihasa_data(Config.DATA_PATH)
            
            if not chunk_docs:
                logger.error("No documents available for FAISS index creation")
                return None
            
            vector_store = FAISS.from_documents(chunk_docs, embedding_model)
            vector_store.save_local(Config.FAISS_INDEX_PATH)
            logger.info(f"✓ New FAISS index created and saved to {Config.FAISS_INDEX_PATH}")
        
        return vector_store
    
    except Exception as e:
        logger.error(f"Failed to initialize vector store: {e}")
        return None


# ============================================================================
# LOCAL LLM SETUP
# ============================================================================

def setup_local_llm(
    base_model_name: str = Config.BASE_MODEL,
    adapter_path: str = Config.ADAPTER_PATH
) -> HuggingFacePipeline:
    """
    Initialize fine-tuned LLM with LoRA adapter and graceful fallback.
    
    Args:
        base_model_name: Name of the base model
        adapter_path: Path to LoRA adapter weights
    
    Returns:
        HuggingFacePipeline instance
    """
    logger.info(f"Setting up LLM: {base_model_name} with adapter from {adapter_path}")
    
    bnb_config = Config.get_bnb_config()
    tokenizer = None
    model = None
    
    try:
        # Load tokenizer
        logger.info(f"Loading tokenizer from {base_model_name}")
        tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        
        # Load base model
        logger.info(f"Loading base model: {base_model_name}")
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True
        )
        
        # Load LoRA adapter
        logger.info(f"Loading LoRA adapter from {adapter_path}")
        model = PeftModel.from_pretrained(base_model, adapter_path)
        model = model.merge_and_unload()
        model.eval()
        
        logger.info(f"✓ Successfully loaded fine-tuned model with LoRA adapter")
    
    except Exception as e:
        logger.warning(f"Failed to load fine-tuned model: {e}")
        logger.info("Falling back to base model")
        
        try:
            tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(
                base_model_name,
                device_map="auto",
                trust_remote_code=True
            )
            logger.info("✓ Loaded base model as fallback")
        except Exception as fallback_error:
            logger.error(f"Failed to load even base model: {fallback_error}")
            raise
    
    # Create pipeline
    logger.info("Creating text generation pipeline")
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=Config.MAX_TOKENS,
        temperature=Config.TEMPERATURE,
        do_sample=True,
        top_p=Config.TOP_P,
        eos_token_id=tokenizer.eos_token_id,
        return_full_text=False
    )
    
    llm = HuggingFacePipeline(pipeline=pipe)
    logger.info("✓ LLM pipeline initialized")
    return llm


# ============================================================================
# PROMPT TEMPLATE
# ============================================================================

def create_qa_prompt() -> PromptTemplate:
    """
    Create the question-answering prompt template.
    
    Returns:
        Configured PromptTemplate instance
    """
    template = """### Human:
CONTEXT:
{context}

Based *only* on the CONTEXT, analyze the most probable verse cited as {context_citation_1}.

QUESTION: {question}

### Assistant:
The most relevant verse is **{context_citation_1}**.

**Sanskrit Text:** {sanskrit_1}

**English Translation:** {english_1}

**Explanation:** [Explain the meaning based on the translation and context, focusing on the first shloka's context and meaning.]
"""
    
    return PromptTemplate(
        template=template,
        input_variables=["context", "question", "context_citation_1", "sanskrit_1", "english_1"]
    )


# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

def format_retrieved_documents(retrieved_docs: List[Document]) -> Tuple[str, Dict]:
    """
    Format retrieved documents into context string and citation information.
    
    Args:
        retrieved_docs: List of retrieved Document objects
    
    Returns:
        Tuple of (formatted_context, first_doc_citation_dict)
    """
    if not retrieved_docs:
        logger.warning("No documents retrieved")
        return "", {}
    
    custom_context_parts = []
    
    for i, doc in enumerate(retrieved_docs):
        meta = doc.metadata
        sanskrit_text = doc.page_content
        english_text = meta.get("english_text", "Translation not available")
        source_citation = f"{meta.get('book')} {meta.get('chapter')}.{meta.get('shloka_num')}"
        
        context_block = f"""
--- SHLOKA {i+1} (Source: {source_citation}) ---
Sanskrit: {sanskrit_text}
English Translation: {english_text}
"""
        custom_context_parts.append(context_block)
    
    custom_context = "\n".join(custom_context_parts)
    
    # Extract first document citation info
    first_doc_meta = retrieved_docs[0].metadata
    first_citation_dict = {
        "citation": f"{first_doc_meta.get('book')} {first_doc_meta.get('chapter')}.{first_doc_meta.get('shloka_num')}",
        "sanskrit": retrieved_docs[0].page_content,
        "english": first_doc_meta.get("english_text", "Translation not available")
    }
    
    logger.debug(f"Formatted {len(retrieved_docs)} documents for context")
    return custom_context, first_citation_dict


def print_source_documents(retrieved_docs: List[Document]) -> None:
    """
    Print formatted source document information.
    
    Args:
        retrieved_docs: List of retrieved Document objects
    """
    print("\n" + "="*70)
    print("📚 Retrieved Sources:")
    print("="*70)
    
    if not retrieved_docs:
        print("No documents retrieved.")
        return
    
    for i, doc in enumerate(retrieved_docs, 1):
        meta = doc.metadata
        print(f"\n[{i}] Source: {meta.get('book')} {meta.get('chapter')}.{meta.get('shloka_num')}")
        print(f"    Sanskrit: {doc.page_content[:80]}...")
        print(f"    English:  {meta.get('english_text', 'N/A')[:80]}...")
    
    print("-"*70)


# ============================================================================
# CHAT INTERFACE
# ============================================================================

def chat_with_assistant(
    llm: HuggingFacePipeline,
    retriever,
    qa_prompt: PromptTemplate
) -> None:
    """
    Interactive chat loop for user queries.
    
    Args:
        llm: Language model instance
        retriever: Document retriever instance
        qa_prompt: Question-answering prompt template
    """
    print("\n" + "="*70)
    print("🏛️  Sanskrit Scripture Research Assistant")
    print("="*70)
    print("\nAsk questions about Sanskrit scriptures.")
    print("Examples: 'What is the nature of the self?' 'Explain dharma'")
    print("Type 'quit' or 'exit' to end the conversation.\n")
    
    logger.info("Chat session started")
    
    while True:
        try:
            user_query = input("\n📚 Your Question: ").strip()
            
            if not user_query:
                print("Please enter a question.")
                continue
            
            if user_query.lower() in ["quit", "exit"]:
                print("\n✅ Thank you for using the Sanskrit Research Assistant. Goodbye!")
                logger.info("Chat session ended by user")
                break
            
            logger.info(f"Processing query: {user_query[:50]}...")
            
            # Retrieve relevant documents
            retrieved_docs = retriever.get_relevant_documents(user_query)
            
            if not retrieved_docs:
                print("\n⚠️ No relevant documents found. Please try a different query.")
                logger.warning(f"No documents retrieved for query: {user_query}")
                continue
            
            # Format documents for the prompt
            custom_context, first_citation = format_retrieved_documents(retrieved_docs)
            
            # Create final prompt
            final_prompt = qa_prompt.format(
                context=custom_context,
                question=user_query,
                context_citation_1=first_citation["citation"],
                sanskrit_1=first_citation["sanskrit"],
                english_1=first_citation["english"]
            )
            
            # Invoke LLM
            logger.info("Invoking LLM for response generation")
            result_text = llm.invoke(final_prompt)
            
            # Display results
            print_source_documents(retrieved_docs)
            print("\n" + "-"*70)
            print("📖 Answer:")
            print("-"*70)
            print(result_text)
            
            logger.info("Response generated and displayed")
        
        except KeyboardInterrupt:
            print("\n\n✅ Interrupted. Exiting assistant.")
            logger.info("Chat session interrupted by user")
            break
        
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            print(f"\n⚠️ An error occurred: {e}")
            print("Please try again with a different question.")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main() -> int:
    """
    Main entry point for the application.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info("="*70)
    logger.info("Starting Sanskrit Scripture RAG Assistant")
    logger.info("="*70)
    
    try:
        # Validate configuration
        if not Config.validate():
            logger.error("Configuration validation failed")
            return 1
        
        # Check CUDA availability
        check_cuda_availability()
        
        # Create necessary directories
        os.makedirs(os.path.dirname(Config.FAISS_INDEX_PATH), exist_ok=True)
        
        # Load data
        logger.info("Loading Sanskrit scripture data...")
        chunks = load_and_chunk_itihasa_data(Config.DATA_PATH)
        
        if not chunks:
            logger.error("No documents loaded. Cannot proceed.")
            return 1
        
        # Initialize vector store
        logger.info("Initializing vector store...")
        vector_store = initialize_vector_store(chunks)
        
        if vector_store is None:
            logger.error("Failed to initialize vector store")
            return 1
        
        retriever = vector_store.as_retriever(k=Config.RETRIEVER_K)
        logger.info(f"✓ Retriever initialized with k={Config.RETRIEVER_K}")
        
        # Setup LLM
        logger.info("Setting up language model...")
        llm = setup_local_llm()
        
        # Create prompt template
        qa_prompt = create_qa_prompt()
        logger.info("✓ QA prompt template created")
        
        logger.info("="*70)
        logger.info("✓ All systems initialized. Starting chat interface...")
        logger.info("="*70)
        
        # Start interactive chat
        chat_with_assistant(llm, retriever, qa_prompt)
        
        logger.info("✓ Application completed successfully")
        return 0
    
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
