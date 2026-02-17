// ========================================================================
// SANSKRITY - Frontend JavaScript
// Handles tabs, chat UI, file uploads, context management, and STT
// ========================================================================

const API_BASE = '';  // Same origin

// ========================================================================
// STATE MANAGEMENT
// ========================================================================

let isRecording = false;
let recognition = null;
let chatHistory = [];

// ========================================================================
// INITIALIZATION
// ========================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeTabs();
    initializeEventListeners();
    loadContextList();
    initializeSpeechRecognition();
    autoResizeTextarea();
});

// ========================================================================
// TAB NAVIGATION
// ========================================================================

function initializeTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            
            // Update button states
            tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(`${tabId}-tab`).classList.add('active');
        });
    });
}

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
    
    const queryInput = document.getElementById('queryInput');
    queryInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            handleQuery();
        }
        // Enter without shift for single-line submit
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
            e.preventDefault();
            handleQuery();
        }
    });
    
    // Auto-resize textarea
    queryInput.addEventListener('input', autoResizeTextarea);

    // Voice input
    document.getElementById('voiceBtn').addEventListener('click', toggleVoiceInput);
}

function autoResizeTextarea() {
    const textarea = document.getElementById('queryInput');
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}

// ========================================================================
// CHAT FUNCTIONS
// ========================================================================

function setQuery(query) {
    document.getElementById('queryInput').value = query;
    autoResizeTextarea();
    document.getElementById('queryInput').focus();
}

function addMessageToChat(type, content, metadata = null) {
    const chatMessages = document.getElementById('chatMessages');
    
    // Remove welcome message if present
    const welcomeMsg = chatMessages.querySelector('.welcome-message');
    if (welcomeMsg) {
        welcomeMsg.remove();
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${type}`;
    
    if (type === 'user') {
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-text">${escapeHtml(content)}</div>
            </div>
            <div class="message-avatar">👤</div>
        `;
    } else if (type === 'assistant') {
        let sourcesHtml = '';
        if (metadata && metadata.scripture_context && metadata.scripture_context.length > 0) {
            sourcesHtml = `
                <div class="message-sources">
                    <div class="sources-toggle" onclick="toggleSources(this)">
                        📚 View Sources (${metadata.scripture_context.length})
                    </div>
                    <div class="sources-content" style="display: none;">
                        ${metadata.scripture_context.map(s => `
                            <div class="source-item">
                                <div class="source-text">${escapeHtml(s.text.substring(0, 200))}...</div>
                                <div class="source-ref">${s.book || ''} ${s.chapter || ''}.${s.shloka_num || ''}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        let citationHtml = '';
        if (metadata && metadata.citation) {
            citationHtml = `<div class="message-citation">📜 ${escapeHtml(metadata.citation)}</div>`;
        }
        
        messageDiv.innerHTML = `
            <div class="message-avatar">🙏</div>
            <div class="message-content">
                ${citationHtml}
                <div class="message-text">${formatResponse(content)}</div>
                ${sourcesHtml}
            </div>
        `;
    } else if (type === 'loading') {
        messageDiv.innerHTML = `
            <div class="message-avatar">🙏</div>
            <div class="message-content">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
    }
    
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageDiv;
}

function toggleSources(element) {
    const sourcesContent = element.nextElementSibling;
    const isHidden = sourcesContent.style.display === 'none';
    sourcesContent.style.display = isHidden ? 'block' : 'none';
    element.textContent = isHidden 
        ? `📚 Hide Sources` 
        : `📚 View Sources (${sourcesContent.querySelectorAll('.source-item').length})`;
}

function formatResponse(text) {
    // Convert line breaks to <br> and preserve paragraphs
    return escapeHtml(text)
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
}

function removeLoadingMessage() {
    const loadingMsg = document.querySelector('.chat-message.loading');
    if (loadingMsg) {
        loadingMsg.remove();
    }
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
                    ${(ctx.file_type || 'text').toUpperCase()} • ${ctx.chunk_count} chunks
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
        autoResizeTextarea();
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
    const queryInput = document.getElementById('queryInput');
    const query = queryInput.value.trim();

    if (!query || query.length < 3) {
        showToast('Please enter a question (at least 3 characters).', 'error');
        return;
    }

    // Add user message to chat
    addMessageToChat('user', query);
    
    // Clear input
    queryInput.value = '';
    autoResizeTextarea();
    
    // Show loading
    addMessageToChat('loading', '');

    try {
        const response = await fetch(`${API_BASE}/api/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query })
        });

        const data = await response.json();

        // Remove loading message
        removeLoadingMessage();

        if (response.ok) {
            addMessageToChat('assistant', data.answer, {
                scripture_context: data.scripture_context,
                citation: data.citation,
                shloka: data.shloka,
                translation: data.translation
            });
        } else {
            throw new Error(data.detail || 'Query failed');
        }
    } catch (error) {
        console.error('Query error:', error);
        removeLoadingMessage();
        addMessageToChat('assistant', `Sorry, an error occurred: ${error.message}`);
        showToast(`Error: ${error.message}`, 'error');
    }
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
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
