"""
FastAPI server for Sanskrity RAG system with context management.
Provides REST API endpoints for file uploads, context management, and enhanced RAG queries.
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import os
from pathlib import Path

from config import Config
from logger import get_logger
from database import get_database
from context_manager import (
    process_file_upload,
    store_user_context,
    list_user_contexts,
    delete_user_context, 
    get_embedding_model
)
# from mongodb_vector_store import search_scripture, search_user_context  # Replaced by local FAISS
from models import setup_local_llm
from rag_chain import create_qa_prompt, initialize_vector_store, get_retriever
from data_loader import load_and_chunk_itihasa_data

logger = get_logger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Sanskrity RAG API",
    description="Sanskrit Scripture RAG system with context management",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
db = None
llm = None
embedding_model = None
retriever = None  # Local FAISS retriever


# Pydantic models for request/response
class TextContextRequest(BaseModel):
    text: str
    title: str = "Untitled"


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    query: str
    answer: str
    shloka: Optional[str] = None
    citation: Optional[str] = None
    translation: Optional[str] = None
    scripture_context: List[dict]
    user_context: List[dict]
    processing_time_ms: float


@app.on_event("startup")
async def startup_event():
    """Initialize database and models on startup."""
    global db, llm, embedding_model, retriever
    
    logger.info("=" * 70)
    logger.info("STARTING SANSKRITY RAG SERVER")
    logger.info("=" * 70)
    
    try:
        # Connect to MongoDB (for user context storage only)
        logger.info("Connecting to MongoDB Atlas...")
        db = await get_database()
        logger.info("✓ MongoDB connected")
        
        # Load embedding model
        logger.info("Loading embedding model...")
        embedding_model = get_embedding_model()
        logger.info("✓ Embedding model loaded")

        # Initialize Local FAISS Vector Store
        logger.info("Initializing Local FAISS Vector Store...")
        # Check if index exists or load from CSV
        if not os.path.exists(Config.FAISS_INDEX_PATH):
            logger.info(f"Index not found at {Config.FAISS_INDEX_PATH}. Loading CSV data...")
            chunks = load_and_chunk_itihasa_data(Config.DATA_PATH)
            vector_store = initialize_vector_store(chunks)
        else:
            logger.info(f"Loading existing index from {Config.FAISS_INDEX_PATH}...")
            vector_store = initialize_vector_store()  # Will load from disk
            
        if vector_store:
            retriever = get_retriever(vector_store)
            logger.info("✓ Local FAISS Retriever initialized")
        else:
            logger.error("Failed to initialize FAISS Vector Store")

        
        # Load LLM (optional - can be loaded on first query if slow)
        logger.info("Loading LLM...")
        llm = setup_local_llm()
        logger.info("✓ LLM loaded")
        
        logger.info("=" * 70)
        logger.info(f"✓ SERVER READY ON http://{Config.SERVER_HOST}:{Config.SERVER_PORT}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global db
    if db:
        await db.close()
        logger.info("Database connection closed")


# ============================================================================
# FRONTEND ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend HTML page."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    
    if frontend_path.exists():
        return frontend_path.read_text()
    else:
        return """
        <html>
            <head><title>Sanskrity RAG</title></head>
            <body>
                <h1>Sanskrity RAG API</h1>
                <p>Frontend not found. API is running at <a href="/docs">/docs</a></p>
            </body>
        </html>
        """


# Mount static files for CSS and JS
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ============================================================================
# CONTEXT MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/api/context/upload")
async def upload_context_file(file: UploadFile = File(...)):
    """
    Upload a PDF, DOCX, or TXT file and convert to vectors.
    
    The file is processed immediately and NOT stored.
    Only text chunks and embeddings are saved to MongoDB.
    """
    try:
        # Validate file type
        file_ext = file.filename.split('.')[-1].lower()
        if file_ext not in Config.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {Config.ALLOWED_EXTENSIONS}"
            )
        
        # Read file content
        file_bytes = await file.read()
        
        # Check file size
        file_size_mb = len(file_bytes) / (1024 * 1024)
        if file_size_mb > Config.MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Max size: {Config.MAX_FILE_SIZE_MB}MB"
            )
        
        logger.info(f"Received file upload: {file.filename} ({file_ext}, {file_size_mb:.2f}MB)")
        
        # Process and store
        result = await process_file_upload(db, file_bytes, file.filename, file_ext)
        
        return {
            "success": True,
            "message": f"File processed successfully",
            **result
        }
    
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/context/text")
async def add_text_context(request: TextContextRequest):
    """
    Add text context directly (no file upload).
    """
    try:
        if not request.text or len(request.text.strip()) < 10:
            raise HTTPException(
                status_code=400,
                detail="Text is too short (minimum 10 characters)"
            )
        
        logger.info(f"Received text context: {request.title} ({len(request.text)} chars)")
        
        # Store text context
        result = await store_user_context(
            db,
            request.text,
            f"{request.title}.txt",
            "text"
        )
        
        return {
            "success": True,
            "message": "Text context stored successfully",
            **result
        }
    
    except Exception as e:
        logger.error(f"Text context storage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/context/list")
async def get_context_list():
    """
    Get list of all uploaded context files.
    """
    try:
        contexts = await list_user_contexts(db)
        return {
            "success": True,
            "contexts": contexts,
            "total": len(contexts)
        }
    
    except Exception as e:
        logger.error(f"Failed to list contexts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/context/{filename}")
async def delete_context(filename: str):
    """
    Delete all chunks associated with a filename.
    """
    try:
        deleted_count = await delete_user_context(db, filename)
        
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="Context not found")
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} chunks",
            "deleted_count": deleted_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RAG QUERY ENDPOINT
# ============================================================================

@app.post("/api/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """
    Process a RAG query with enhanced context from both scripture and user uploads.
    
    Flow:
    1. Create query embedding
    2. Search scripture vectors
    3. Search user context vectors
    4. Combine contexts
    5. Send to LLM for final response
    """
    import time
    start_time = time.time()
    
    try:
        if not request.query or len(request.query.strip()) < 3:
            raise HTTPException(
                status_code=400,
                detail="Query is too short (minimum 3 characters)"
            )
        
        logger.info(f"Processing query: {request.query}")
        
        # 1. Search Local FAISS Index (replaces scripture_vectors search)
        if retriever:
            scripture_docs = retriever.invoke(request.query)
        else:
            logger.warning("Local retriever not initialized!")
            scripture_docs = []
            
        scripture_context_list = []
        for doc in scripture_docs:
            meta = doc.metadata
            scripture_context_list.append({
                "text": doc.page_content,
                "source": meta.get("source_file", "Local CSV"),
                "english_text": meta.get("english_text", "Translation not available"),
                "book": meta.get("book", ""),
                "chapter": meta.get("chapter", ""),
                "shloka_num": meta.get("shloka_num", ""),
                "score": 0.0  # FAISS via retriever doesn't return score easily
            })
        
        # Extract top scripture details for the boxes
        top_shloka = None
        top_citation = None
        top_translation = None
        
        if scripture_context_list:
            top_result = scripture_context_list[0]
            top_shloka = top_result["text"]
            
            # Construct meaningful citation
            book = top_result.get('book', 'Scripture')
            chapter = top_result.get('chapter', '?')
            shloka = top_result.get('shloka_num', '?')
            top_citation = f"{book} {chapter}.{shloka}"
            
            top_translation = top_result.get("english_text")
            
            # VERBOSE LOGGING
            logger.info("--- TOP RAG RESULT ---")
            logger.info(f"CITATION: {top_citation}")
            logger.info(f"SHLOKA: {top_shloka[:50]}...")
            logger.info(f"TRANSLATION: {top_translation[:50]}...")
            logger.info("----------------------")
        
        # 3. Search user context vectors (DISABLED FOR LOCAL MODE)
        # user_results = await search_user_context(db, query_embedding)
        user_context_list = [] 
        # [
        #     {
        #         "text": text,
        #         "filename": metadata.get("original_filename", "Unknown"),
        #         "score": score
        #     }
        #     for text, metadata, score in user_results
        # ]
        
        # 4. Combine contexts for LLM
        scripture_text = "\n\n".join([r["text"] for r in scripture_context_list])
        user_text = "\n\n".join([r["text"] for r in user_context_list])
        
        # Build prompt - ask for summary/explanation
        if user_text:
            prompt_text = f"""### Human:
You are a Sanskrit scripture scholar.

SCRIPTURE CONTEXT:
{scripture_text}

ADDITIONAL USER CONTEXT:
{user_text}

QUESTION: {request.query}

Based on the scripture and additional user context provided, please provide a comprehensive summary and explanation. 
Do not just repeat the translation. Analyze the meaning and connect it to the user's question.
Provide the response in English.

### Assistant:
"""
        else:
            prompt_text = f"""### Human:
You are a Sanskrit scripture scholar.

CONTEXT:
{scripture_text}

QUESTION: {request.query}

Based on the scripture context provided, please provide a comprehensive summary and explanation.
Do not just repeat the translation. Analyze the meaning and connect it to the user's question.
Provide the response in English.

### Assistant:
"""
        
        logger.info(f"Prompt sent to LLM:\n{prompt_text}")

        # 5. Generate LLM response
        logger.info("Generating LLM summary...")
        answer = llm.invoke(prompt_text)
        
        # Clean up answer
        if isinstance(answer, dict):
            answer = answer.get('text', str(answer))
        answer = answer.strip()
        
        # Log the generated answer
        logger.info(f"LLM Generated Summary: {answer[:100]}...")
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"Query processed in {processing_time:.2f}ms")
        
        return QueryResponse(
            query=request.query,
            answer=answer,  # This is the Summary Box
            shloka=top_shloka,    # Box 1
            citation=top_citation, # Box 1 side
            translation=top_translation, # Box 2
            scripture_context=scripture_context_list,
            user_context=user_context_list,
            processing_time_ms=processing_time
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected" if db and db.client else "disconnected",
        "llm": "loaded" if llm else "not loaded",
        "embedding_model": "loaded" if embedding_model else "not loaded"
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "server:app",
        host=Config.SERVER_HOST,
        port=Config.SERVER_PORT,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )
