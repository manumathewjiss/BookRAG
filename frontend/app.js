// ========================================================================
// SANSKRITY - Frontend JavaScript
// Handles file uploads, context management, STT, and query processing
// ========================================================================

const API_BASE = '';  // Same origin

// ========================================================================
// STATE MANAGEMENT
// ========================================================================

let isRecording = false;
let recognition = null;

// ========================================================================
// INITIALIZATION
// ========================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    loadContextList();
    initializeSpeechRecognition();
});

// ========================================================================
// EVENT LISTENERS
// ========================================================================

function initializeEventListeners() {
    // File upload
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleFileDrop);

    // Text context
    document.getElementById('addTextBtn').addEventListener('click', handleTextContext);

    // Query submission
    document.getElementById('submitBtn').addEventListener('click', handleQuery);
    document.getElementById('queryInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
            handleQuery();
        }
    });

    // Voice input
    document.getElementById('voiceBtn').addEventListener('click', toggleVoiceInput);
}

// ========================================================================
// FILE UPLOAD
// ========================================================================

function handleDragOver(e) {
    e.preventDefault();
    e.currentTarget.classList.add('drag-over');
}

function handleDragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
}

function handleFileDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        uploadFile(files[0]);
    }
}

function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) {
        uploadFile(files[0]);
    }
}

async function uploadFile(file) {
    // Validate file type
    const allowedTypes = ['pdf', 'docx', 'txt'];
    const fileExt = file.name.split('.').pop().toLowerCase();

    if (!allowedTypes.includes(fileExt)) {
        showToast('Invalid file type. Please upload PDF, DOCX, or TXT files.', 'error');
        return;
    }

    // Validate file size (10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showToast('File too large. Maximum size is 10MB.', 'error');
        return;
    }

    // Show progress
    showUploadProgress(true);

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE}/api/context/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showToast(`✓ ${file.name} processed successfully! ${data.chunks_stored} chunks created.`, 'success');
            loadContextList();
        } else {
            throw new Error(data.detail || 'Upload failed');
        }
    } catch (error) {
        console.error('Upload error:', error);
        showToast(`Error: ${error.message}`, 'error');
    } finally {
        showUploadProgress(false);
        document.getElementById('fileInput').value = '';
    }
}

function showUploadProgress(show) {
    const uploadArea = document.getElementById('uploadArea');
    const uploadProgress = document.getElementById('uploadProgress');

    if (show) {
        uploadArea.style.display = 'none';
        uploadProgress.style.display = 'block';

        // Animate progress bar
        const progressFill = document.getElementById('progressFill');
        progressFill.style.width = '0%';
        setTimeout(() => progressFill.style.width = '90%', 100);
    } else {
        uploadArea.style.display = 'block';
        uploadProgress.style.display = 'none';
        document.getElementById('progressFill').style.width = '0%';
    }
}

// ========================================================================
// TEXT CONTEXT
// ========================================================================

async function handleTextContext() {
    const title = document.getElementById('textTitle').value.trim() || 'Untitled';
    const text = document.getElementById('textContent').value.trim();

    if (!text || text.length < 10) {
        showToast('Please enter at least 10 characters of text.', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/context/text`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text, title })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showToast(`✓ Text context added! ${data.chunks_stored} chunks created.`, 'success');
            document.getElementById('textTitle').value = '';
            document.getElementById('textContent').value = '';
            loadContextList();
        } else {
            throw new Error(data.detail || 'Failed to add text context');
        }
    } catch (error) {
        console.error('Text context error:', error);
        showToast(`Error: ${error.message}`, 'error');
    }
}

// ========================================================================
// CONTEXT LIST
// ========================================================================

async function loadContextList() {
    try {
        const response = await fetch(`${API_BASE}/api/context/list`);
        const data = await response.json();

        if (response.ok && data.success) {
            renderContextList(data.contexts);
        } else {
            throw new Error('Failed to load context list');
        }
    } catch (error) {
        console.error('Load context list error:', error);
    }
}

function renderContextList(contexts) {
    const container = document.getElementById('contextList');

    if (!contexts || contexts.length === 0) {
        container.innerHTML = '<p class="text-center" style="color: var(--text-tertiary);">No context uploaded yet</p>';
        return;
    }

    container.innerHTML = contexts.map(ctx => `
        <div class="context-item">
            <div class="context-info">
                <div class="context-filename">${escapeHtml(ctx.filename)}</div>
                <div class="context-meta">
                    ${ctx.file_type.toUpperCase()} • ${ctx.chunk_count} chunks
                </div>
            </div>
            <button class="context-delete" onclick="deleteContext('${escapeHtml(ctx.filename)}')" title="Delete">
                🗑️
            </button>
        </div>
    `).join('');
}

async function deleteContext(filename) {
    if (!confirm(`Delete "${filename}"?`)) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/context/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showToast(`✓ Deleted ${filename}`, 'success');
            loadContextList();
        } else {
            throw new Error(data.detail || 'Delete failed');
        }
    } catch (error) {
        console.error('Delete error:', error);
        showToast(`Error: ${error.message}`, 'error');
    }
}

// ========================================================================
// SPEECH-TO-TEXT (STT)
// ========================================================================

function initializeSpeechRecognition() {
    // Check browser support
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        console.warn('Speech recognition not supported');
        document.getElementById('voiceBtn').style.display = 'none';
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
        isRecording = true;
        document.getElementById('voiceBtn').classList.add('recording');
        showToast('🎤 Listening...', 'success');
    };

    recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
            .map(result => result[0].transcript)
            .join('');

        document.getElementById('queryInput').value = transcript;
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        isRecording = false;
        document.getElementById('voiceBtn').classList.remove('recording');
        showToast(`Error: ${event.error}`, 'error');
    };

    recognition.onend = () => {
        isRecording = false;
        document.getElementById('voiceBtn').classList.remove('recording');
    };
}

function toggleVoiceInput() {
    if (!recognition) {
        showToast('Speech recognition not available', 'error');
        return;
    }

    if (isRecording) {
        recognition.stop();
    } else {
        recognition.start();
    }
}

// ========================================================================
// QUERY PROCESSING
// ========================================================================

async function handleQuery() {
    const query = document.getElementById('queryInput').value.trim();

    if (!query || query.length < 3) {
        showToast('Please enter a question (at least 3 characters).', 'error');
        return;
    }

    // Show loading state
    showLoading(true);
    hideResponse();

    try {
        const response = await fetch(`${API_BASE}/api/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query })
        });

        const data = await response.json();

        if (response.ok) {
            displayResponse(data);
            showToast(`✓ Query processed in ${data.processing_time_ms.toFixed(0)}ms`, 'success');
        } else {
            throw new Error(data.detail || 'Query failed');
        }
    } catch (error) {
        console.error('Query error:', error);
        showToast(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
    }
}

function showLoading(show) {
    document.getElementById('loadingState').style.display = show ? 'block' : 'none';
}

function hideResponse() {
    document.getElementById('responseSection').style.display = 'none';
}

function displayResponse(data) {
    // Show response section
    const responseSection = document.getElementById('responseSection');
    responseSection.style.display = 'block';

    // Display answer
    document.getElementById('answerContent').textContent = data.answer;

    // Display scripture sources
    const scriptureContainer = document.getElementById('scriptureSources');
    if (data.scripture_context && data.scripture_context.length > 0) {
        scriptureContainer.innerHTML = data.scripture_context.map(source => `
            <div class="source-item">
                <div class="source-text">${escapeHtml(source.text.substring(0, 150))}...</div>
                <div class="source-ref">${escapeHtml(source.source)} (relevance: ${(source.score * 100).toFixed(1)}%)</div>
            </div>
        `).join('');
    } else {
        scriptureContainer.innerHTML = '<p class="text-center" style="color: var(--text-tertiary);">No sources found</p>';
    }

    // Display user context sources
    const userSourcesSection = document.getElementById('userSourcesSection');
    const userContainer = document.getElementById('userSources');

    if (data.user_context && data.user_context.length > 0) {
        userSourcesSection.style.display = 'block';
        userContainer.innerHTML = data.user_context.map(source => `
            <div class="source-item">
                <div class="source-text">${escapeHtml(source.text.substring(0, 150))}...</div>
                <div class="source-ref">${escapeHtml(source.filename)} (relevance: ${(source.score * 100).toFixed(1)}%)</div>
            </div>
        `).join('');
    } else {
        userSourcesSection.style.display = 'none';
    }

    // Scroll to response
    responseSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ========================================================================
// UTILITIES
// ========================================================================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
