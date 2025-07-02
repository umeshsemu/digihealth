// Authentication Management
class AuthManager {
    constructor() {
        this.token = localStorage.getItem('auth_token');
        this.userEmail = localStorage.getItem('user_email');
        this.userId = localStorage.getItem('user_id');
        this.isAuthenticated = !!this.token;
        
        this.init();
    }

    init() {
        this.setupModal();
        this.setupEventListeners();
        this.setupHamburgerMenu();
        this.updateUI();
        this.checkAuthStatus();
    }

    setupModal() {
        this.modal = document.getElementById('auth-modal');
        this.authBtn = document.getElementById('auth-btn');
        this.authText = document.getElementById('auth-text');
        this.modalTitle = document.getElementById('modal-title');
        this.closeBtn = document.querySelector('.close');
        this.loginForm = document.getElementById('login-form');
        this.signupForm = document.getElementById('signup-form');
        this.switchToSignup = document.getElementById('switch-to-signup');
        this.switchToLogin = document.getElementById('switch-to-login');
    }

    setupHamburgerMenu() {
        this.hamburgerBtn = document.getElementById('hamburger-menu');
        this.navMenu = document.querySelector('.nav-menu');
        
        if (this.hamburgerBtn) {
            this.hamburgerBtn.addEventListener('click', () => {
                this.toggleHamburgerMenu();
            });
        }

        // Close hamburger menu when clicking outside
        document.addEventListener('click', (e) => {
            if (this.navMenu && this.navMenu.classList.contains('open') && 
                !this.navMenu.contains(e.target) && 
                !this.hamburgerBtn.contains(e.target)) {
                this.closeHamburgerMenu();
            }
        });

        // Close hamburger menu when clicking on a nav link
        if (this.navMenu) {
            this.navMenu.addEventListener('click', (e) => {
                if (e.target.classList.contains('nav-link') || 
                    e.target.classList.contains('auth-btn') ||
                    e.target.closest('.nav-link') ||
                    e.target.closest('.auth-btn')) {
                    this.closeHamburgerMenu();
                }
            });
        }
    }

    toggleHamburgerMenu() {
        if (this.navMenu) {
            this.navMenu.classList.toggle('open');
            this.hamburgerBtn.classList.toggle('active');
        }
    }

    closeHamburgerMenu() {
        if (this.navMenu) {
            this.navMenu.classList.remove('open');
            this.hamburgerBtn.classList.remove('active');
        }
    }

    setupEventListeners() {
        // Auth button click
        this.authBtn.addEventListener('click', () => {
            if (this.isAuthenticated) {
                this.logout();
            } else {
                this.showModal();
            }
        });

        // Modal close
        this.closeBtn.addEventListener('click', () => this.hideModal());
        window.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.hideModal();
            }
        });

        // Form switches
        this.switchToSignup.addEventListener('click', (e) => {
            e.preventDefault();
            this.showSignupForm();
        });

        this.switchToLogin.addEventListener('click', (e) => {
            e.preventDefault();
            this.showLoginForm();
        });

        // Form submissions
        this.loginForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleLogin();
        });

        this.signupForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleSignup();
        });

        // Protected links and actions
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('protected-link') || 
                e.target.classList.contains('protected-action')) {
                e.preventDefault();
                if (!this.isAuthenticated) {
                    this.showModal();
                } else {
                    this.handleProtectedAction(e.target);
                }
            }
        });
    }

    showModal() {
        this.modal.style.display = 'block';
        this.showLoginForm();
    }

    hideModal() {
        this.modal.style.display = 'none';
        this.clearForms();
    }

    showLoginForm() {
        this.loginForm.style.display = 'flex';
        this.signupForm.style.display = 'none';
        this.modalTitle.textContent = 'Login to DigiHealth';
    }

    showSignupForm() {
        this.loginForm.style.display = 'none';
        this.signupForm.style.display = 'flex';
        this.modalTitle.textContent = 'Sign Up for DigiHealth';
    }

    clearForms() {
        this.loginForm.reset();
        this.signupForm.reset();
        this.clearMessages();
    }

    clearMessages() {
        const messages = document.querySelectorAll('.error-message, .success-message');
        messages.forEach(msg => msg.remove());
    }

    showMessage(message, type = 'error') {
        this.clearMessages();
        const messageDiv = document.createElement('div');
        messageDiv.className = `${type}-message`;
        messageDiv.textContent = message;
        
        const activeForm = this.loginForm.style.display !== 'none' ? this.loginForm : this.signupForm;
        activeForm.insertBefore(messageDiv, activeForm.firstChild);
    }

    async handleLogin() {
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;

        if (!email || !password) {
            this.showMessage('Please fill in all fields');
            return;
        }

        try {
            const response = await fetch('/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email, password })
            });

            const data = await response.json();

            if (response.ok) {
                this.setAuthData(data.access_token, data.user_email, data.user_id);
                this.showMessage('Login successful!', 'success');
                setTimeout(() => {
                    this.hideModal();
                    this.updateUI();
                }, 1000);
            } else {
                this.showMessage(data.detail || 'Login failed');
            }
        } catch (error) {
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                this.showMessage('Network error. Please check your connection and try again.');
            } else {
                this.showMessage('An unexpected error occurred. Please try again.');
            }
        }
    }

    async handleSignup() {
        const email = document.getElementById('signup-email').value;
        const password = document.getElementById('signup-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;

        if (!email || !password || !confirmPassword) {
            this.showMessage('Please fill in all fields');
            return;
        }

        if (password !== confirmPassword) {
            this.showMessage('Passwords do not match');
            return;
        }

        if (password.length < 6) {
            this.showMessage('Password must be at least 6 characters long');
            return;
        }

        try {
            const response = await fetch('/auth/signup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email, password, confirm_password: confirmPassword })
            });

            const data = await response.json();

            if (response.ok) {
                this.showMessage('Account created successfully! Please check your email for verification.', 'success');
                setTimeout(() => {
                    this.showLoginForm();
                }, 2000);
            } else {
                this.showMessage(data.detail || 'Signup failed');
            }
        } catch (error) {
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                this.showMessage('Network error. Please check your connection and try again.');
            } else {
                this.showMessage('An unexpected error occurred. Please try again.');
            }
        }
    }

    async logout() {
        try {
            const response = await fetch('/auth/logout', {
                method: 'GET',
                headers: this.getAuthHeaders()
            });

            if (response.status !== 200) {
                // Continue with local cleanup even if server logout fails
            }
        } catch (error) {
            // Continue with local cleanup despite logout error
        }

        // Always clear local data
        this.clearAuthData();
        this.updateUI();
        window.location.href = '/';
    }

    setAuthData(token, email, userId) {
        this.token = token;
        this.userEmail = email;
        this.userId = userId;
        this.isAuthenticated = true;

        localStorage.setItem('auth_token', token);
        localStorage.setItem('user_email', email);
        localStorage.setItem('user_id', userId);
    }

    clearAuthData() {
        this.token = null;
        this.userEmail = null;
        this.userId = null;
        this.isAuthenticated = false;

        localStorage.removeItem('auth_token');
        localStorage.removeItem('user_email');
        localStorage.removeItem('user_id');
    }

    updateUI() {
        if (this.isAuthenticated) {
            this.authText.textContent = this.userEmail || 'Logout';
            this.authBtn.classList.add('authenticated');
            
            // Enable protected elements
            document.querySelectorAll('.protected-link, .protected-action').forEach(el => {
                el.classList.remove('disabled');
            });
        } else {
            this.authText.textContent = 'Login';
            this.authBtn.classList.remove('authenticated');
            
            // Disable protected elements
            document.querySelectorAll('.protected-link, .protected-action').forEach(el => {
                el.classList.add('disabled');
            });
        }
    }

    async checkAuthStatus() {
        if (!this.token) {
            this.updateUI();
            return;
        }

        try {
            const response = await fetch('/auth/verify', {
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });

            const data = await response.json();

            if (!data.authenticated) {
                this.clearAuthData();
                this.updateUI();
            }
        } catch (error) {
            this.clearAuthData();
            this.updateUI();
        }
    }

    handleProtectedAction(element) {
        const action = element.dataset.action;
        const href = element.href;

        if (action === 'upload') {
            window.location.href = '/upload';
        } else if (action === 'query') {
            window.location.href = '/query';
        } else if (action === 'index') {
            window.location.href = '/index';
        } else if (href) {
            window.location.href = href;
        }
    }

    // Method to get auth headers for API calls
    getAuthHeaders() {
        return {
            'Authorization': `Bearer ${this.token}`,
            'Content-Type': 'application/json'
        };
    }
}

// Initialize authentication when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.authManager = new AuthManager();
});

// Export for use in other scripts
window.AuthManager = AuthManager; 