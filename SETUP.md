# Sanskrity Web Frontend Setup Guide

## 🚀 Quick Start

This guide will help you set up and run the Sanskrity RAG system with the new web frontend.

## Prerequisites

- Python 3.8+
- MongoDB Atlas account (connection string provided in config)
- 10GB+ disk space
- 8GB+ RAM (for LLM)
- CUDA-capable GPU (recommended)

## Installation Steps

### 1. Install Dependencies

```bash
cd /home/vyshakh/Documents/Sanskrity
pip install -r requirements.txt
```

New dependencies added:
- `fastapi` - Web server framework
- `uvicorn` - ASGI server  
- `motor` - Async MongoDB driver
- `pymongo[srv]` - MongoDB driver with Atlas support
- `PyPDF2` - PDF processing
- `python-docx` - DOCX processing
- `python-multipart` - File upload support
- `aiofiles` - Async file operations

### 2. Configure MongoDB Atlas Vector Search Index

**IMPORTANT**: You must create vector search indexes in MongoDB Atlas UI before running the migration.

1. Go to MongoDB Atlas → Database → Search
2. Create a new `Search Index` with type **"Vector Search"**
3. Select database: `sanskrity`, collection: `scripture_vectors`
4. Use this configuration:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    }
  ]
}
```

5. Name it: `scripture_vectors_vector_index`
6. Repeat for `user_context_vectors` collection with the same config
7. Name it: `user_context_vectors_vector_index`

### 3. Migrate Scripture Data to MongoDB

Run the migration script to populate the `scripture_vectors` collection:

```bash
cd /home/vyshakh/Documents/Sanskrity
python src/migrate_to_mongodb.py
```

This will:
- Load data from `res/combined.csv`
- Generate embeddings using `multilingual-e5-large`
- Store ~1000s of vector documents in MongoDB
- Display stats and index configuration

**Note**: This may take 10-30 minutes depending on your data size.

### 4. Test Vector Search (Optional)

After migration, test the vector search:

```bash
python src/migrate_to_mongodb.py test
```

This will run a sample query to verify everything works.

### 5. Start the Web Server

```bash
cd /home/vyshakh/Documents/Sanskrity
python src/server.py
```

The server will:
- Connect to MongoDB Atlas
- Load the embedding model
- Load the LLM (this may take a few minutes)
- Start the web server on `http://localhost:8000`

You should see:
```
✓ SERVER READY ON http://0.0.0.0:8000
```

### 6. Access the Web Interface

Open your browser and go to:
```
http://localhost:8000
```

## Features

### Context Management
- **Upload Files**: Drag-and-drop or click to upload PDF, DOCX, or TXT files
- **Add Text**: Paste text directly into the context input
- **View Contexts**: See all uploaded contexts with chunk counts
- **Delete Contexts**: Remove contexts you no longer need

### Query Interface
- **Text Input**: Type your question in the query box
- **Voice Input (STT)**: Click the microphone button to speak your question
- **Enhanced Responses**: Get answers enriched with both scripture and your custom context
- **Source Citations**: See which scriptures and user contexts were used

### Speech-to-Text (STT)
- Uses browser's Web Speech API (no backend needed)
- Click the microphone button to start
- Speaks your question aloud
- Real-time transcription
- Works in Chrome, Edge, Safari

## API Endpoints

The server provides these REST API endpoints:

- `GET /` - Frontend HTML
- `GET /health` - Health check
- `POST /api/context/upload` - Upload file (PDF, DOCX, TXT)
- `POST /api/context/text` - Add text context
- `GET /api/context/list` - List all contexts
- `DELETE /api/context/{filename}` - Delete context
- `POST /api/query` - Process RAG query

API documentation: `http://localhost:8000/docs`

## Architecture

### Backend Flow
```
User Query
  ↓
1. Create query embedding
  ↓
2. Vector search in scripture_vectors (MongoDB)
  ↓
3. Vector search in user_context_vectors (MongoDB)
  ↓
4. Combine contexts
  ↓
5. Send to LLM
  ↓
6. Return answer with citations
```

### Data Storage
- **MongoDB Database**: `sanskrity`
- **Collections**:
  - `scripture_vectors`: Scripture data with embeddings
  - `user_context_vectors`: User-uploaded context with embeddings
- **No file storage**: PDFs and DOCX files are processed and discarded immediately
- **Vector dimensions**: 1024 (multilingual-e5-large)

## Troubleshooting

### MongoDB Connection Issues
- Check your MongoDB Atlas connection string in `src/config.py`
- Ensure your IP is whitelisted in MongoDB Atlas
- Verify network connectivity

### Vector Search Not Working
- Ensure you created the vector search indexes in Atlas
- Index names must match: `scripture_vectors_vector_index` and `user_context_vectors_vector_index`
- Wait a few minutes after creating indexes (they need to build)

### LLM Loading Slowly
- First load takes time (downloading model weights)
- Subsequent starts are faster
- Consider using a smaller model for faster loading

### File Upload Issues
- Max file size: 10MB
- Supported: PDF, DOCX, TXT only
- Check browser console for errors

### Speech Recognition Not Working
- STT only works in HTTPS or localhost
- Requires microphone permissions
- Supported browsers: Chrome, Edge, Safari
- Not supported: Firefox (yet)

## Development

### Auto-reload Mode
```bash
uvicorn src.server:app --reload --host 0.0.0.0 --port 8000
```

### View Logs
Logs are written to `logs/sanskrit_rag.log`

### Configuration
Edit `src/config.py` to change:
- MongoDB connection
- File size limits
- Chunk sizes
- Retrieval parameters
- Server port

## Production Deployment

For production deployment:
1. Set environment variables for sensitive data
2. Use a production ASGI server (gunicorn + uvicorn)
3. Set up HTTPS (required for STT)
4. Configure CORS for your domain
5. Enable authentication/authorization
6. Set up monitoring and logging

## File Structure

```
Sanskrity/
├── src/
│   ├── server.py                 # FastAPI server
│   ├── database.py               # MongoDB connection
│   ├── mongodb_vector_store.py   # Vector search operations
│   ├── context_manager.py        # File processing
│   ├── migrate_to_mongodb.py     # Migration script
│   ├── config.py                 # Configuration
│   └── [other existing files]
├── frontend/
│   ├── index.html               # Main HTML page
│   ├── styles.css               # Premium CSS
│   └── app.js                   # JavaScript logic
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Support

For issues or questions:
1. Check the logs in `logs/sanskrit_rag.log`
2. Verify MongoDB Atlas connection and indexes
3. Test with the migration script first
4. Check browser console for frontend errors

## License

[Your license here]
