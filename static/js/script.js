// Upload functionality
document.addEventListener('DOMContentLoaded', function() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const browseFiles = document.getElementById('browseFiles');
    const uploadProgress = document.getElementById('uploadProgress');
    const uploadResult = document.getElementById('uploadResult');
    const uploadError = document.getElementById('uploadError');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');

    // Only initialize upload functionality if we're on the upload page
    if (!uploadArea) return;

    // Browse files click handler
    browseFiles.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Create a new file input to ensure change event fires
        const newFileInput = document.createElement('input');
        newFileInput.type = 'file';
        newFileInput.accept = '.pdf,.jpg,.jpeg,.png';
        newFileInput.style.display = 'none';
        
        // Add change event listener to new input
        newFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                uploadFile(file);
            }
            // Clean up the temporary input
            document.body.removeChild(newFileInput);
        });
        
        // Add to DOM and trigger click
        document.body.appendChild(newFileInput);
        newFileInput.click();
    });

    // Upload area click handler
    uploadArea.addEventListener('click', (e) => {
        // Don't trigger if clicking on the browse link
        if (e.target === browseFiles || e.target.closest('#browseFiles')) {
            return;
        }
        // Create a new file input to ensure change event fires
        const newFileInput = document.createElement('input');
        newFileInput.type = 'file';
        newFileInput.accept = '.pdf,.jpg,.jpeg,.png';
        newFileInput.style.display = 'none';
        
        // Add change event listener to new input
        newFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                uploadFile(file);
            }
            // Clean up the temporary input
            document.body.removeChild(newFileInput);
        });
        
        // Add to DOM and trigger click
        document.body.appendChild(newFileInput);
        newFileInput.click();
    });

    // Drag and drop handlers
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadFile(files[0]);
        }
    });

    // File upload function
    function uploadFile(file) {
        // Check authentication
        if (!window.authManager || !window.authManager.isAuthenticated) {
            showError('Please login to upload files.');
            return;
        }

        // Validate file type
        const allowedTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
        if (!allowedTypes.includes(file.type)) {
            showError('Unsupported file type. Please upload PDF, JPG, JPEG, or PNG files.');
            return;
        }

        // Validate file size (max 10MB)
        const maxSize = 10 * 1024 * 1024; // 10MB
        if (file.size > maxSize) {
            showError('File size too large. Please upload files smaller than 10MB.');
            return;
        }

        // Hide other sections and show progress
        hideAllSections();
        uploadProgress.style.display = 'block';

        // Create FormData
        const formData = new FormData();
        formData.append('file', file);

        // Simulate progress for better UX
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += Math.random() * 15;
            if (progress > 90) {
                progress = 90;
                clearInterval(progressInterval);
            }
            updateProgress(progress, 'Uploading and processing...');
        }, 200);

        // Get auth headers
        const headers = {};
        if (window.authManager && window.authManager.token) {
            headers['Authorization'] = `Bearer ${window.authManager.token}`;
        }

        // Upload file
        fetch('/upload-file', {
            method: 'POST',
            headers: headers,
            body: formData
        })
        .then(response => {
            clearInterval(progressInterval);
            updateProgress(95, 'Processing complete...');
            
            if (!response.ok) {
                if (response.status === 401) {
                    // Authentication error
                    window.authManager.clearAuthData();
                    window.authManager.updateUI();
                    return Promise.reject({ detail: 'Session expired. Please login again.' });
                } else if (response.status === 409) {
                    // Duplicate file error
                    return response.json().then(err => Promise.reject({ 
                        detail: err.detail || 'Document already exists. Please use a different filename.' 
                    }));
                }
                return response.json().then(err => Promise.reject(err));
            }
            return response.json();
        })
        .then(data => {
            updateProgress(100, 'Upload complete!');
            setTimeout(() => {
                showSuccess(data);
            }, 500);
        })
        .catch(error => {
            clearInterval(progressInterval);
            showError(error.detail || 'An error occurred while uploading the file.');
        });
    }

    // Update progress bar
    function updateProgress(percent, text) {
        progressFill.style.width = percent + '%';
        progressText.textContent = text;
    }

    // Show success result
    function showSuccess(data) {
        hideAllSections();
        uploadResult.style.display = 'block';
        
        document.getElementById('resultFileName').textContent = data.filename;
        document.getElementById('summaryContent').textContent = data.summary;
    }

    // Show error
    function showError(message) {
        hideAllSections();
        uploadError.style.display = 'block';
        
        const errorMessageElement = document.getElementById('errorMessage');
        
        // Check if it's a duplicate file error
        if (message.includes('already exists') || message.includes('Document already exists')) {
            errorMessageElement.innerHTML = `
                <i class="fas fa-exclamation-triangle" style="color: #ff9800; margin-right: 8px;"></i>
                <strong>Document Already Exists</strong><br>
                <span style="font-size: 0.9em; color: #666;">${message}</span><br>
                <span style="font-size: 0.8em; color: #999;">Please use a different filename or check if the document was already uploaded.</span>
            `;
        } else {
            errorMessageElement.innerHTML = `
                <i class="fas fa-exclamation-circle" style="color: #f44336; margin-right: 8px;"></i>
                <strong>Upload Failed</strong><br>
                <span style="font-size: 0.9em; color: #666;">${message}</span>
            `;
        }
    }

    // Hide all sections
    function hideAllSections() {
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'none';
        uploadError.style.display = 'none';
    }

    // Reset upload (make this function global)
    window.resetUpload = function() {
        hideAllSections();
        uploadArea.style.display = 'block';
        // Clear the file input completely
        fileInput.value = '';
        // Reset progress
        progressFill.style.width = '0%';
        progressText.textContent = 'Uploading...';
    };
});

// Query functionality
document.addEventListener('DOMContentLoaded', function() {
    const queryForm = document.getElementById('queryForm');
    
    // Only initialize if we're on the query page
    if (!queryForm) return;
    
    queryForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // Check authentication
        if (!window.authManager || !window.authManager.isAuthenticated) {
            window.authManager.showModal();
            return;
        }
        
        const queryInput = document.getElementById('queryInput');
        const loadingIndicator = document.getElementById('loadingIndicator');
        const resultContainer = document.getElementById('resultContainer');
        const errorContainer = document.getElementById('errorContainer');
        const answerElement = document.getElementById('answer');
        const sourcesElement = document.getElementById('sources');
        const processingTimeElement = document.getElementById('processingTime');
        const errorMessageElement = document.getElementById('errorMessage');
        
        // Validate input
        if (!queryInput.value.trim()) {
            errorMessageElement.textContent = 'Please enter a question';
            errorContainer.style.display = 'block';
            return;
        }
        
        // Reset UI
        resultContainer.style.display = 'none';
        errorContainer.style.display = 'none';
        loadingIndicator.style.display = 'flex';
        
        try {
            const headers = {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${window.authManager.token}`
            };
            
            const response = await fetch('/process-query', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    query: queryInput.value.trim()
                })
            });
            
            if (!response.ok) {
                if (response.status === 401) {
                    // Authentication error
                    window.authManager.clearAuthData();
                    window.authManager.updateUI();
                    throw new Error('Session expired. Please login again.');
                } else if (response.status === 500) {
                    throw new Error('Server error. Please try again later.');
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || 'Query processing failed');
                }
            }
            
            const data = await response.json();
            
            // Display answer
            answerElement.textContent = data.answer;
            
            // Display sources
            if (data.sources && data.sources.length > 0) {
                sourcesElement.innerHTML = data.sources.map(source => `
                    <div class="source-item">
                        <div class="source-header">
                            <span class="similarity-score">Similarity: ${source.similarity_score.toFixed(1)}%</span>
                            <div class="document-actions">
                                <button class="btn btn-primary btn-small view-document-btn" 
                                        onclick="viewDocument('${source.document_id}', '${source.filename}')"
                                        title="View document in browser">
                                    <i class="fas fa-eye"></i> View
                                </button>
                            </div>
                        </div>
                        <div class="source-content">
                            <div class="document-info">
                                <strong>File:</strong> ${source.filename}
                            </div>
                            <div class="summary-text">
                                ${source.summary}
                            </div>
                        </div>
                    </div>
                `).join('');
            } else {
                sourcesElement.innerHTML = '<p>No sources found</p>';
            }
            
            // Display processing time
            if (data.processing_time) {
                processingTimeElement.textContent = `Processed in ${data.processing_time.toFixed(2)} seconds`;
            }
            
            // Show results
            resultContainer.style.display = 'block';
            
        } catch (error) {
            errorMessageElement.textContent = error.message || 'An unexpected error occurred';
            errorContainer.style.display = 'block';
        } finally {
            loadingIndicator.style.display = 'none';
        }
    });
});

// Document Viewer functionality
class DocumentViewer {
    constructor() {
        this.currentPage = 1;
        this.totalPages = 1;
        this.zoomLevel = 1;
        this.isDragging = false;
        this.dragStart = { x: 0, y: 0 };
        this.currentOffset = { x: 0, y: 0 };
        this.documentType = null;
        this.documentData = null;
        this.objectUrl = null;
        
        this.initializeElements();
        this.bindEvents();
    }
    
    initializeElements() {
        this.modal = document.getElementById('document-modal');
        this.viewer = document.getElementById('document-viewer');
        this.title = document.getElementById('document-title');
        this.downloadBtn = document.getElementById('download-from-modal');
        
        // Page navigation
        this.prevBtn = document.getElementById('prev-page');
        this.nextBtn = document.getElementById('next-page');
        this.pageInfo = document.getElementById('page-info');
        this.currentPageSpan = document.getElementById('current-page');
        this.totalPagesSpan = document.getElementById('total-pages');
        
        // Zoom controls
        this.zoomOutBtn = document.getElementById('zoom-out');
        this.zoomInBtn = document.getElementById('zoom-in');
        this.zoomLevelSpan = document.getElementById('zoom-level');
        this.fitPageBtn = document.getElementById('fit-page');
    }
    
    bindEvents() {
        // Page navigation
        this.prevBtn.addEventListener('click', () => this.previousPage());
        this.nextBtn.addEventListener('click', () => this.nextPage());
        
        // Zoom controls
        this.zoomOutBtn.addEventListener('click', () => this.zoomOut());
        this.zoomInBtn.addEventListener('click', () => this.zoomIn());
        this.fitPageBtn.addEventListener('click', () => this.fitToPage());
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => this.handleKeyboard(e));
        
        // Mouse wheel zoom
        this.viewer.addEventListener('wheel', (e) => this.handleWheel(e));
    }
    
    async loadDocument(documentId, filename) {
        try {
            this.showLoading();
            this.title.textContent = filename;
            
            // Download document
            const headers = {
                'Authorization': `Bearer ${window.authManager.token}`
            };
            
            const response = await fetch(`/download-document/${documentId}`, {
                method: 'GET',
                headers: headers
            });
            
            if (!response.ok) {
                throw new Error('Failed to load document');
            }
            
            const blob = await response.blob();
            this.objectUrl = URL.createObjectURL(blob);
            this.documentData = blob;
            
            const fileExtension = filename.split('.').pop().toLowerCase();
            
            if (fileExtension === 'pdf') {
                await this.loadPDF();
            } else if (['jpg', 'jpeg', 'png'].includes(fileExtension)) {
                await this.loadImage();
            } else {
                this.showUnsupported();
            }
            
            // Setup download button
            this.downloadBtn.style.display = 'inline-block';
            this.downloadBtn.onclick = () => this.downloadDocument(filename);
            
        } catch (error) {
            this.showError(error.message);
        }
    }
    
    async loadPDF() {
        this.documentType = 'pdf';
        this.currentPage = 1;
        
        // Create PDF viewer with page navigation
        this.viewer.innerHTML = `
            <div class="pdf-viewer-container">
                <iframe src="${this.objectUrl}#page=${this.currentPage}" 
                        class="pdf-iframe" 
                        title="PDF Document">
                </iframe>
            </div>
        `;
        
        // Try to detect total pages (this is a best effort approach)
        try {
            // Create a temporary iframe to check PDF properties
            const tempIframe = document.createElement('iframe');
            tempIframe.style.display = 'none';
            tempIframe.src = this.objectUrl;
            document.body.appendChild(tempIframe);
            
            // Wait a bit for PDF to load, then try to get page count
            setTimeout(() => {
                try {
                    // This is a fallback - most browsers don't allow access to PDF content
                    // We'll start with 1 page and let users navigate
                    this.totalPages = 1;
                    this.updatePageInfo();
                } catch (e) {
                    this.totalPages = 1;
                    this.updatePageInfo();
                } finally {
                    document.body.removeChild(tempIframe);
                }
            }, 1000);
        } catch (e) {
            this.totalPages = 1;
            this.updatePageInfo();
        }
        
        // Show PDF controls
        this.showPDFControls();
        this.updatePageInfo();
    }
    
    async loadImage() {
        this.documentType = 'image';
        this.currentPage = 1;
        this.totalPages = 1;
        
        // Create image viewer with zoom/pan
        this.viewer.innerHTML = `
            <div class="image-viewer-container">
                <img src="${this.objectUrl}" 
                     alt="Document Image" 
                     class="document-image"
                     draggable="false">
            </div>
        `;
        
        const img = this.viewer.querySelector('.document-image');
        img.addEventListener('load', () => {
            this.setupImageControls(img);
        });
        
        // Show image controls
        this.showImageControls();
        this.updateZoomInfo();
    }
    
    setupImageControls(img) {
        // Mouse events for panning
        img.addEventListener('mousedown', (e) => this.startDrag(e));
        img.addEventListener('mousemove', (e) => this.drag(e));
        img.addEventListener('mouseup', () => this.endDrag());
        img.addEventListener('mouseleave', () => this.endDrag());
        
        // Touch events for mobile
        img.addEventListener('touchstart', (e) => this.startDrag(e));
        img.addEventListener('touchmove', (e) => this.drag(e));
        img.addEventListener('touchend', () => this.endDrag());
        
        // Initial fit to page
        this.fitToPage();
    }
    
    showPDFControls() {
        this.prevBtn.style.display = 'inline-block';
        this.nextBtn.style.display = 'inline-block';
        this.pageInfo.style.display = 'inline-block';
        this.zoomOutBtn.style.display = 'inline-block';
        this.zoomInBtn.style.display = 'inline-block';
        this.zoomLevelSpan.style.display = 'inline-block';
        this.fitPageBtn.style.display = 'inline-block';
        
        // Add click handler to page info for manual page count setting
        this.pageInfo.style.cursor = 'pointer';
        this.pageInfo.title = 'Click to set total pages';
        this.pageInfo.onclick = () => this.setTotalPages();
    }
    
    showImageControls() {
        this.prevBtn.style.display = 'none';
        this.nextBtn.style.display = 'none';
        this.pageInfo.style.display = 'none';
        this.zoomOutBtn.style.display = 'inline-block';
        this.zoomInBtn.style.display = 'inline-block';
        this.zoomLevelSpan.style.display = 'inline-block';
        this.fitPageBtn.style.display = 'inline-block';
    }
    
    hideControls() {
        this.prevBtn.style.display = 'none';
        this.nextBtn.style.display = 'none';
        this.pageInfo.style.display = 'none';
        this.zoomOutBtn.style.display = 'none';
        this.zoomInBtn.style.display = 'none';
        this.zoomLevelSpan.style.display = 'none';
        this.fitPageBtn.style.display = 'none';
    }
    
    previousPage() {
        if (this.currentPage > 1) {
            this.currentPage--;
            this.updatePDFPage();
            this.updatePageInfo();
        }
    }
    
    nextPage() {
        if (this.currentPage < this.totalPages) {
            this.currentPage++;
            this.updatePDFPage();
            this.updatePageInfo();
        }
    }
    
    updatePDFPage() {
        const iframe = this.viewer.querySelector('.pdf-iframe');
        if (iframe) {
            iframe.src = `${this.objectUrl}#page=${this.currentPage}`;
            
            // Update button states
            this.prevBtn.disabled = this.currentPage <= 1;
            this.nextBtn.disabled = this.currentPage >= this.totalPages;
        }
    }
    
    updatePageInfo() {
        this.currentPageSpan.textContent = this.currentPage;
        this.totalPagesSpan.textContent = this.totalPages;
    }
    
    zoomIn() {
        if (this.zoomLevel < 3) {
            this.zoomLevel += 0.25;
            this.applyZoom();
        }
    }
    
    zoomOut() {
        if (this.zoomLevel > 0.25) {
            this.zoomLevel -= 0.25;
            this.applyZoom();
        }
    }
    
    fitToPage() {
        this.zoomLevel = 1;
        this.currentOffset = { x: 0, y: 0 };
        this.applyZoom();
    }
    
    applyZoom() {
        const img = this.viewer.querySelector('.document-image');
        if (img) {
            img.style.transform = `scale(${this.zoomLevel}) translate(${this.currentOffset.x}px, ${this.currentOffset.y}px)`;
            this.updateZoomInfo();
        }
    }
    
    updateZoomInfo() {
        this.zoomLevelSpan.textContent = `${Math.round(this.zoomLevel * 100)}%`;
    }
    
    startDrag(e) {
        if (this.zoomLevel > 1) {
            this.isDragging = true;
            const point = e.touches ? e.touches[0] : e;
            this.dragStart = { x: point.clientX, y: point.clientY };
            e.preventDefault();
        }
    }
    
    drag(e) {
        if (this.isDragging) {
            const point = e.touches ? e.touches[0] : e;
            const deltaX = point.clientX - this.dragStart.x;
            const deltaY = point.clientY - this.dragStart.y;
            
            this.currentOffset.x += deltaX / this.zoomLevel;
            this.currentOffset.y += deltaY / this.zoomLevel;
            
            this.dragStart = { x: point.clientX, y: point.clientY };
            this.applyZoom();
            e.preventDefault();
        }
    }
    
    endDrag() {
        this.isDragging = false;
    }
    
    handleWheel(e) {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            if (e.deltaY < 0) {
                this.zoomIn();
            } else {
                this.zoomOut();
            }
        }
    }
    
    handleKeyboard(e) {
        if (!this.modal.style.display || this.modal.style.display === 'none') return;
        
        switch(e.key) {
            case 'ArrowLeft':
                if (this.documentType === 'pdf') this.previousPage();
                break;
            case 'ArrowRight':
                if (this.documentType === 'pdf') this.nextPage();
                break;
            case '+':
            case '=':
                this.zoomIn();
                break;
            case '-':
                this.zoomOut();
                break;
            case '0':
                this.fitToPage();
                break;
            case 'Escape':
                this.close();
                break;
        }
    }
    
    downloadDocument(filename) {
        if (this.objectUrl) {
            const a = document.createElement('a');
            a.href = this.objectUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showMessage(`Document "${filename}" downloaded successfully!`, 'success');
        }
    }
    
    showLoading() {
        this.hideControls();
        this.viewer.innerHTML = `
            <div class="loading-document">
                <div class="spinner"></div>
                <p>Loading document...</p>
            </div>
        `;
    }
    
    showError(message) {
        this.hideControls();
        this.viewer.innerHTML = `
            <div class="error-viewing">
                <i class="fas fa-exclamation-circle"></i>
                <h3>Error Loading Document</h3>
                <p>${message}</p>
            </div>
        `;
    }
    
    showUnsupported() {
        this.hideControls();
        this.viewer.innerHTML = `
            <div class="unsupported-file">
                <i class="fas fa-file"></i>
                <h3>File Preview Not Available</h3>
                <p>This file type cannot be previewed in the browser.</p>
                <p>Please use the download button to view the file.</p>
            </div>
        `;
    }
    
    open() {
        this.modal.style.display = 'block';
    }
    
    close() {
        if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = null;
        }
        this.modal.style.display = 'none';
        this.reset();
    }
    
    reset() {
        this.currentPage = 1;
        this.zoomLevel = 1;
        this.isDragging = false;
        this.dragStart = { x: 0, y: 0 };
        this.currentOffset = { x: 0, y: 0 };
        this.documentType = null;
        this.documentData = null;
        this.hideControls();
    }
    
    setTotalPages() {
        const totalPages = prompt('Enter the total number of pages in this PDF:', this.totalPages);
        if (totalPages && !isNaN(totalPages) && parseInt(totalPages) > 0) {
            this.totalPages = parseInt(totalPages);
            this.updatePageInfo();
            this.updatePDFPage();
            showMessage(`PDF page count set to ${this.totalPages} pages`, 'success');
        }
    }
}

// Initialize document viewer
let documentViewer = null;
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('document-modal')) {
        documentViewer = new DocumentViewer();
    }
});

// Function to view document in modal
async function viewDocument(documentId, filename) {
    try {
        // Check authentication
        if (!window.authManager || !window.authManager.isAuthenticated) {
            window.authManager.showModal();
            return;
        }
        
        // Open viewer and load document
        documentViewer.open();
        await documentViewer.loadDocument(documentId, filename);
        
    } catch (error) {
        showMessage(error.message || 'Error viewing document. Please try again.', 'error');
    }
}

// Function to close document modal
function closeDocumentModal() {
    if (documentViewer) {
        documentViewer.close();
    }
}

// Utility function to show messages
function showMessage(message, type = 'info') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(messageDiv);
    
    // Trigger animation
    setTimeout(() => messageDiv.classList.add('show'), 100);
    
    // Remove after 3 seconds
    setTimeout(() => {
        messageDiv.classList.remove('show');
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.parentNode.removeChild(messageDiv);
            }
        }, 300);
    }, 3000);
}

// Smooth scrolling for anchor links
document.addEventListener('DOMContentLoaded', function() {
    const links = document.querySelectorAll('a[href^="#"]');
    
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
});

// Add loading animation to buttons
document.addEventListener('DOMContentLoaded', function() {
    const buttons = document.querySelectorAll('.btn');
    
    buttons.forEach(button => {
        button.addEventListener('click', function(e) {
            // Don't add loading to upload buttons or reset buttons
            if (this.onclick || this.getAttribute('onclick') || this.type === 'button') {
                return;
            }
            
            // Add loading state for navigation buttons
            const originalText = this.innerHTML;
            this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
            this.style.pointerEvents = 'none';
            
            // Reset after 2 seconds (for demo purposes)
            setTimeout(() => {
                this.innerHTML = originalText;
                this.style.pointerEvents = 'auto';
            }, 2000);
        });
    });
});

// Add animations on scroll
document.addEventListener('DOMContentLoaded', function() {
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);

    // Observe elements for animation
    const animatedElements = document.querySelectorAll('.feature-card, .tip-card, .suggestion-item, .step');
    
    animatedElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

// Add typing effect to hero title (only on homepage)
document.addEventListener('DOMContentLoaded', function() {
    const heroTitle = document.querySelector('.hero-content h1');
    
    if (heroTitle && heroTitle.textContent.includes('AI-Powered Healthcare')) {
        const text = heroTitle.textContent;
        heroTitle.textContent = '';
        
        let i = 0;
        const typeWriter = () => {
            if (i < text.length) {
                heroTitle.textContent += text.charAt(i);
                i++;
                setTimeout(typeWriter, 50);
            }
        };
        
        // Start typing effect after a small delay
        setTimeout(typeWriter, 500);
    }
});