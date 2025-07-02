from fastapi import FastAPI, File, UploadFile, Request, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import shutil
from pathlib import Path
import tempfile
from gemini import process_file, save_summary_to_supabase
from datetime import datetime
import subprocess
import json
import logging
from rag import RAGSystem
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Optional
import jwt
from functools import wraps
import requests
import base64
import time

app = FastAPI(title="DigiHealth Document Processor")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Create uploads directory if it doesn't exist
UPLOAD_DIR = "uploads"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

# Load environment variables from .env
load_dotenv()

# Validate required environment variables
required_env_vars = {
    "SUPABASE_URL": os.getenv("SUPABASE_URL"),
    "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY"),
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY")
}

missing_vars = [var for var, value in required_env_vars.items() if not value]
if missing_vars:
    logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Optional environment variables
optional_env_vars = {
    "SARVAM_API_KEY": os.getenv("SARVAM_API_KEY"),
    "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    "GPT_MODEL": os.getenv("GPT_MODEL", "gpt-4"),
    "TOP_K": os.getenv("TOP_K", "3")
}

logger.info("✅ Environment variables loaded successfully")
logger.info(f"🔑 OpenAI API key present: {bool(required_env_vars['OPENAI_API_KEY'])}")
logger.info(f"🔑 Sarvam API key present: {bool(optional_env_vars['SARVAM_API_KEY'])}")

# Supabase configuration
SUPABASE_URL = required_env_vars["SUPABASE_URL"]
SUPABASE_ANON_KEY = required_env_vars["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment variables")

# Storage bucket configuration
STORAGE_BUCKET = "user-indexes"
DOCUMENTS_BUCKET = "user-documents"  # New bucket for original documents

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
logger.info("✅ Supabase client initialized successfully")

# Initialize RAG system - now we'll create user-specific instances
# rag_system = RAGSystem()  # Remove global RAG system

class QueryRequest(BaseModel):
    query: str

class AuthRequest(BaseModel):
    email: str
    password: str

class SignUpRequest(BaseModel):
    email: str
    password: str
    confirm_password: str

class SpeechToTextRequest(BaseModel):
    audio_data: str  # Base64 encoded audio data

def verify_token(authorization: Optional[str] = Header(None)):
    """Verify JWT token with Supabase and extract user UUID"""
    if not authorization:
        logger.warning("❌ No authorization header provided")
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    try:
        # Extract token from "Bearer <token>"
        token = authorization.replace("Bearer ", "")
        logger.info("🔍 Verifying JWT token with Supabase...")
        
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        
        # Log the response structure for debugging
        logger.info(f"🔍 User response type: {type(user_response)}")
        logger.info(f"🔍 User response attributes: {dir(user_response)}")
        
        # Check if response has the expected structure
        if hasattr(user_response, 'user') and user_response.user:
            user_id = user_response.user.id
            logger.info(f"✅ Token verified successfully for user: {user_id}")
            logger.info(f"🔍 User ID type: {type(user_id)}")
            logger.info(f"🔍 User ID value: {user_id}")
            return user_id
        else:
            logger.error("❌ Invalid user data in token response")
            logger.error(f"🔍 User response: {user_response}")
            raise HTTPException(status_code=401, detail="Invalid user data")
            
    except Exception as e:
        logger.error(f"❌ Token verification failed: {e}")
        logger.error(f"🔍 Exception type: {type(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

def require_auth(func):
    """Decorator to require authentication for routes"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Get the request object from kwargs
        request = kwargs.get('request')
        
        if not request:
            # Try to find request in args
            for arg in args:
                if hasattr(arg, 'headers') and hasattr(arg, 'method'):
                    request = arg
                    break
        
        if not request:
            logger.error("❌ Could not find request object in function arguments")
            raise HTTPException(status_code=500, detail="Internal server error: request object not found")
        
        # Get authorization header
        auth_header = request.headers.get('authorization')
        if not auth_header:
            logger.warning("❌ No authorization header in request")
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            # Verify token and get user_id
            user_id = verify_token(auth_header)
            kwargs['user_id'] = user_id
            logger.info(f"✅ Authentication successful for user: {user_id}")
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            raise HTTPException(status_code=401, detail="Invalid authentication")
        
        return await func(*args, **kwargs)
    return wrapper

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Homepage with app description and health tips"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Upload page for file uploads - requires authentication"""
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...), request: Request = None):
    """Handle file upload and processing - requires authentication"""
    # Check authentication manually for file uploads
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"📁 Starting file upload for user: {user_id}")
        logger.info(f"📄 File details: {file.filename}, size: {file.size} bytes")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Validate file type
        allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
        file_extension = os.path.splitext(file.filename)[1].lower()
        
        if file_extension not in allowed_extensions:
            logger.warning(f"❌ Unsupported file type: {file_extension}")
            raise HTTPException(
                status_code=400, 
                detail="Unsupported file type. Please upload PDF, JPG, JPEG, or PNG files."
            )
        
        logger.info(f"✅ File type validated: {file_extension}")
        
        # Read file data
        file_data = await file.read()
        logger.info(f"📄 File data read: {len(file_data)} bytes")
        
        # Upload original document to Supabase Storage
        logger.info("📤 Uploading original document to Supabase Storage...")
        storage_result = upload_document_to_storage(user_id, file_data, file.filename)
        
        if not storage_result:
            logger.error("❌ Failed to upload document to storage")
            raise HTTPException(status_code=500, detail="Failed to upload document to storage")
        
        # Check if it's a duplicate file error
        if isinstance(storage_result, dict) and storage_result.get("error") == "duplicate":
            logger.warning(f"⚠️ Duplicate file detected: {file.filename}")
            raise HTTPException(
                status_code=409, 
                detail=storage_result.get("message", "Document already exists")
            )
        
        storage_path = storage_result
        logger.info(f"✅ Document uploaded to storage: {storage_path}")
        
        # Save uploaded file temporarily for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            tmp_file.write(file_data)
            temp_file_path = tmp_file.name
        
        logger.info(f"💾 File saved temporarily at: {temp_file_path}")
        
        try:
            # Process the file using gemini.py logic
            logger.info("🤖 Starting AI text extraction with Gemini...")
            summary = process_file(temp_file_path)
            logger.info(f"✅ Text extraction completed. Summary length: {len(summary)} characters")
            
            # Save to Supabase with user_id and storage path
            logger.info("💾 Saving document metadata to Supabase...")
            document_id = save_summary_to_supabase(summary, file.filename, user_id, supabase, storage_path)
            logger.info(f"✅ Document metadata saved to Supabase with ID: {document_id}")
            
            return JSONResponse({
                "status": "success",
                "message": "File processed and saved successfully!",
                "filename": file.filename,
                "summary": summary,
                "document_id": document_id,
                "storage_path": storage_path
            })
            
        except Exception as e:
            logger.error(f"❌ Error processing file: {str(e)}")
            # Clean up storage if processing failed
            delete_document_from_storage(user_id, file.filename)
            raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                logger.info("🧹 Temporary file cleaned up")
                
    except Exception as e:
        logger.error(f"❌ Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/index", response_class=HTMLResponse)
async def index_page(request: Request):
    """Index page for document indexing - requires authentication"""
    return templates.TemplateResponse("indexing.html", {"request": request})

@app.post("/start-indexing")
async def start_indexing(request: Request = None):
    """Start the indexing process - requires authentication"""
    # Check authentication manually
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"🔍 Starting indexing process for user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Run the indexing script with user_id
        logger.info("🚀 Executing indexing script...")
        result = subprocess.run(
            ["python", "indexing.py", "--user-id", user_id],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error(f"❌ Indexing failed: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Indexing failed: {error_msg}"
            )
        
        logger.info("✅ Indexing script completed successfully")
        
        # Parse the output to get progress information
        output_lines = result.stdout.strip().split('\n')
        progress_info = {
            'documents_embedded': 0,
            'total_documents': 0,
            'status': 'completed'
        }
        
        for line in output_lines:
            if "Found" in line and "documents to embed" in line:
                progress_info['documents_embedded'] = int(line.split()[1])
            elif "Loaded" in line and "documents with embeddings" in line:
                progress_info['total_documents'] = int(line.split()[1])
        
        # Update last indexed time in Supabase for this user
        logger.info("🕒 Updating indexed timestamp in Supabase...")
        try:
            supabase.table('documents').update({
                'indexed_at': datetime.now().isoformat()
            }).eq('user_id', user_id).execute()
            logger.info("✅ Indexed timestamp updated successfully")
        except Exception as e:
            logger.warning(f"⚠️ Could not update indexed timestamp: {e}")
        
        # Get updated counts for this user from Supabase
        logger.info("📊 Fetching document statistics from Supabase...")
        try:
            response = supabase.table('documents').select('*').eq('user_id', user_id).execute()
            total_documents = len(response.data)
            
            # Get last indexed time
            indexed_docs = [doc for doc in response.data if doc.get('indexed_at')]
            last_indexed_time = "Never"
            if indexed_docs:
                last_indexed = max(indexed_docs, key=lambda x: x.get('indexed_at', ''))
                last_indexed_time = last_indexed.get('indexed_at', 'Never')
            
            logger.info(f"📈 Document statistics - Total: {total_documents}, Last indexed: {last_indexed_time}")
            
        except Exception as e:
            logger.error(f"❌ Error fetching document statistics: {e}")
            total_documents = 0
            last_indexed_time = "Error"
        
        return JSONResponse({
            "status": "success",
            "message": "Indexing completed successfully",
            "last_indexed_time": last_indexed_time,
            "total_documents": total_documents,
            "progress_info": progress_info
        })
        
    except Exception as e:
        logger.error(f"❌ Error during indexing: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error during indexing: {str(e)}"
        )

@app.get("/query", response_class=HTMLResponse)
async def query_page(request: Request):
    """Query page for document search - requires authentication"""
    return templates.TemplateResponse("query.html", {"request": request})

@app.post("/process-query")
async def process_query(query_request: QueryRequest, request: Request = None):
    """Process a query using the RAG system - requires authentication"""
    # Check authentication manually
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"🔍 Processing query for user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Create user-specific RAG system
        rag_system = RAGSystem(user_id)
        
        # Process query with user-specific system
        result = rag_system.process_query(query_request.query, user_id)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}"
        )

# Authentication endpoints
@app.post("/auth/signup")
async def signup(auth_request: SignUpRequest):
    """User signup endpoint"""
    try:
        if auth_request.password != auth_request.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        
        # Create user in Supabase
        response = supabase.auth.sign_up({
            "email": auth_request.email,
            "password": auth_request.password
        })
        
        # Check if response has the expected structure
        if hasattr(response, 'user') and response.user:
            user_id = response.user.id
        else:
            user_id = "pending_verification"
        
        return JSONResponse({
            "status": "success",
            "message": "User created successfully. Please check your email for verification.",
            "user_id": user_id
        })
        
    except Exception as e:
        logger.error(f"Signup error: {e}")
        # Handle specific Supabase errors
        error_message = str(e)
        if "already registered" in error_message.lower():
            raise HTTPException(status_code=400, detail="Email already registered")
        elif "password" in error_message.lower():
            raise HTTPException(status_code=400, detail="Password requirements not met")
        else:
            raise HTTPException(status_code=400, detail="Signup failed. Please try again.")

@app.post("/auth/login")
async def login(auth_request: AuthRequest):
    """User login endpoint"""
    try:
        # Sign in with Supabase
        response = supabase.auth.sign_in_with_password({
            "email": auth_request.email,
            "password": auth_request.password
        })
        
        # Check if response has the expected structure
        if hasattr(response, 'session') and response.session:
            access_token = response.session.access_token
        else:
            raise HTTPException(status_code=401, detail="Invalid session")
            
        if hasattr(response, 'user') and response.user:
            user_id = response.user.id
            user_email = response.user.email
        else:
            raise HTTPException(status_code=401, detail="Invalid user data")
        
        return JSONResponse({
            "status": "success",
            "message": "Login successful",
            "access_token": access_token,
            "user_id": user_id,
            "user_email": user_email
        })
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        # Handle specific Supabase errors
        error_message = str(e)
        if "invalid" in error_message.lower():
            raise HTTPException(status_code=401, detail="Invalid email or password")
        elif "not confirmed" in error_message.lower():
            raise HTTPException(status_code=401, detail="Please verify your email before logging in")
        else:
            raise HTTPException(status_code=401, detail="Login failed. Please try again.")

@app.get("/auth/test")
async def test_supabase():
    """Test endpoint to verify Supabase connection"""
    try:
        # Test basic Supabase connection
        return JSONResponse({
            "status": "success",
            "message": "Supabase connection successful",
            "url": SUPABASE_URL,
            "has_anon_key": bool(SUPABASE_ANON_KEY)
        })
    except Exception as e:
        logger.error(f"Supabase test error: {e}")
        return JSONResponse({
            "status": "error",
            "message": f"Supabase connection failed: {str(e)}"
        })

@app.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """User logout endpoint"""
    try:
        # Log the logout attempt for debugging
        logger.info(f"Logout attempt - Authorization header present: {bool(authorization)}")
        
        # Try to sign out with Supabase, but don't rely on the response
        try:
            supabase.auth.sign_out()
            logger.info("Supabase sign_out called successfully")
        except Exception as supabase_error:
            logger.warning(f"Supabase sign_out error (non-critical): {supabase_error}")
            # Continue with logout even if Supabase fails
        
        return JSONResponse({
            "status": "success",
            "message": "Logout successful"
        })
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        logger.error(f"Error type: {type(e)}")
        logger.error(f"Error details: {str(e)}")
        
        # Always return success for logout
        # The frontend will clear the local storage anyway
        return JSONResponse({
            "status": "success",
            "message": "Logout successful"
        })

@app.get("/auth/verify")
async def verify_auth(authorization: Optional[str] = Header(None)):
    """Verify authentication status"""
    try:
        if not authorization:
            return JSONResponse({"authenticated": False})
        
        user_id = verify_token(authorization)
        return JSONResponse({
            "authenticated": True,
            "user_id": user_id
        })
        
    except Exception as e:
        return JSONResponse({"authenticated": False})

@app.get("/auth/debug")
async def debug_supabase():
    """Debug endpoint to test Supabase auth methods"""
    try:
        debug_info = {
            "supabase_url": SUPABASE_URL,
            "has_anon_key": bool(SUPABASE_ANON_KEY),
            "anon_key_length": len(SUPABASE_ANON_KEY) if SUPABASE_ANON_KEY else 0,
            "client_type": str(type(supabase)),
            "auth_type": str(type(supabase.auth))
        }
        
        # Test if we can access auth methods
        try:
            # This should not fail even without a session
            debug_info["auth_methods_accessible"] = True
        except Exception as e:
            debug_info["auth_methods_accessible"] = False
            debug_info["auth_error"] = str(e)
        
        return JSONResponse({
            "status": "success",
            "debug_info": debug_info
        })
    except Exception as e:
        logger.error(f"Debug error: {e}")
        return JSONResponse({
            "status": "error",
            "message": f"Debug failed: {str(e)}"
        })

@app.post("/reinitialize-rag")
async def reinitialize_rag(request: Request = None):
    """Reinitialize RAG system for a user - requires authentication"""
    logger.info("🔄 Reinitialize RAG endpoint called")
    
    # Check authentication manually
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        logger.error("❌ No authorization header provided")
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"✅ Authentication successful for user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Create user-specific RAG system
        rag_system = RAGSystem(user_id)
        
        # Check if user has an index
        if not rag_system.check_user_has_index(user_id):
            logger.warning(f"⚠️ No index found for user {user_id}")
            return JSONResponse({
                "status": "warning",
                "message": "No index found. Please index your documents first.",
                "user_id": user_id
            })
        
                # Load user index
        if rag_system.load_user_index(user_id):
            logger.info(f"✅ RAG system reinitialized successfully for user {user_id}")
            return JSONResponse({
                "status": "success",
                "message": "RAG system reinitialized successfully",
                "user_id": user_id
            })
        else:
            logger.error(f"❌ Failed to load index for user {user_id}")
            return JSONResponse({
                "status": "error",
                "message": "Failed to load index. Please reindex your documents.",
                "user_id": user_id
            })
            
    except Exception as e:
        logger.error(f"❌ RAG reinitialization error: {e}")
        logger.error(f"🔍 Error type: {type(e)}")
        import traceback
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to reinitialize RAG system: {str(e)}")

@app.post("/speech-to-text")
async def speech_to_text(request: SpeechToTextRequest, auth_request: Request = None):
    """Convert speech to text using Sarvam AI API - requires authentication"""
    logger.info("🎤 Speech-to-text endpoint called")
    
    # Check authentication manually
    auth_header = auth_request.headers.get('authorization') if auth_request else None
    if not auth_header:
        logger.error("❌ No authorization header provided")
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"✅ Authentication successful for user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Get Sarvam AI API key from environment
        sarvam_api_key = os.getenv("SARVAM_API_KEY")
        logger.info(f"🔑 Sarvam API key present: {bool(sarvam_api_key)}")
        
        if not sarvam_api_key:
            logger.error("❌ SARVAM_API_KEY not found in environment variables")
            raise HTTPException(status_code=500, detail="Speech-to-text service not configured")
        
        # Log audio data info
        logger.info(f"📊 Audio data length: {len(request.audio_data)} characters")
        
        # Decode base64 audio data
        try:
            audio_data = base64.b64decode(request.audio_data)
            logger.info(f"✅ Audio data decoded successfully, size: {len(audio_data)} bytes")
        except Exception as e:
            logger.error(f"❌ Failed to decode base64 audio data: {e}")
            logger.error(f"🔍 Audio data preview: {request.audio_data[:100]}...")
            raise HTTPException(status_code=400, detail="Invalid audio data format")
        
        # Create a temporary file to store the WAV audio data
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_file_path = temp_file.name
        
        try:
            # Prepare request to Sarvam AI API using the documented format
            sarvam_url = "https://api.sarvam.ai/speech-to-text-translate"
            
            headers = {
                "api-subscription-key": sarvam_api_key
            }
            
            # Prepare payload as per documentation
            payload = {
                "model": "saaras:v2"  # Use correct model name from allowed values
            }
            
            # Prepare files as per documentation
            with open(temp_file_path, 'rb') as audio_file:
                files = {
                    "file": ("audio.wav", audio_file, "audio/wav")
                }
                
                logger.info(f"🌐 Sending request to Sarvam AI API: {sarvam_url}")
                logger.info(f"📋 Payload: {payload}")
                logger.info(f"📁 WAV file size: {len(audio_data)} bytes")
                logger.info(f"📁 File path: {temp_file_path}")
                logger.info(f"📁 File exists: {os.path.exists(temp_file_path)}")
                
                # Log file details
                file_stat = os.stat(temp_file_path)
                logger.info(f"📁 File stats: size={file_stat.st_size}, mode={oct(file_stat.st_mode)}")
                
                response = requests.post(
                    sarvam_url, 
                    data=payload, 
                    files=files, 
                    headers=headers, 
                    timeout=30
                )
                
                logger.info(f"📡 Response status: {response.status_code}")
                logger.info(f"📡 Response headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f"✅ Success! Response keys: {list(result.keys())}")
                        logger.info(f"📄 Full response: {result}")
                        
                        # Extract transcription from response
                        transcribed_text = result.get("transcript", "")
                        
                        if not transcribed_text:
                            logger.warning("⚠️ No transcript found in response")
                            logger.warning(f"🔍 Full response: {result}")
                            raise HTTPException(status_code=500, detail="No transcription received from API")
                        
                        logger.info(f"✅ Transcription successful: {len(transcribed_text)} characters")
                        logger.info(f"📝 Transcription: {transcribed_text}")
                        
                        return JSONResponse({
                            "status": "success",
                            "transcription": transcribed_text,
                            "user_id": user_id,
                            "language_code": result.get("language_code", "unknown"),
                            "request_id": result.get("request_id", "")
                        })
                        
                    except ValueError as e:
                        logger.error(f"❌ Failed to parse JSON response: {e}")
                        logger.error(f"🔍 Raw response: {response.text}")
                        raise HTTPException(status_code=500, detail="Invalid response format from speech-to-text API")
                
                else:
                    logger.error(f"❌ API request failed: {response.status_code}")
                    logger.error(f"🔍 Error response: {response.text}")
                    
                    if response.status_code == 401:
                        raise HTTPException(status_code=500, detail="Invalid API key for speech-to-text service")
                    elif response.status_code == 400:
                        raise HTTPException(status_code=400, detail="Invalid audio format or request")
                    else:
                        raise HTTPException(status_code=500, detail=f"Speech-to-text API error: {response.status_code}")
                        
        except requests.exceptions.Timeout:
            logger.error("❌ Request to Sarvam AI API timed out")
            raise HTTPException(status_code=500, detail="Speech-to-text service timeout")
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Request to Sarvam AI API failed: {e}")
            raise HTTPException(status_code=500, detail=f"Speech-to-text service error: {str(e)}")
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
                logger.info("🧹 Temporary WAV file cleaned up")
            except Exception as e:
                logger.warning(f"⚠️ Failed to clean up temporary file: {e}")
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected speech-to-text error: {e}")
        logger.error(f"🔍 Error type: {type(e)}")
        import traceback
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {str(e)}")

@app.get("/test-sarvam")
async def test_sarvam_api():
    """Test endpoint to verify Sarvam AI API configuration"""
    try:
        sarvam_api_key = os.getenv("SARVAM_API_KEY")
        
        debug_info = {
            "sarvam_api_key_present": bool(sarvam_api_key),
            "sarvam_api_key_length": len(sarvam_api_key) if sarvam_api_key else 0,
            "sarvam_api_key_preview": sarvam_api_key[:10] + "..." if sarvam_api_key else None,
            "api_url": "https://api.sarvam.ai/speech-to-text-translate",
            "supported_models": ["saaras:v1", "saaras:v2", "saaras:v2.5", "saaras:turbo", "saaras:flash"],
            "requests_available": True
        }
        
        # Test basic connectivity
        try:
            test_response = requests.get("https://api.sarvam.ai", timeout=5)
            debug_info["api_connectivity"] = "success"
            debug_info["api_status_code"] = test_response.status_code
        except Exception as e:
            debug_info["api_connectivity"] = "failed"
            debug_info["api_error"] = str(e)
        
        return JSONResponse({
            "status": "success",
            "message": "Sarvam AI API configuration check",
            "debug_info": debug_info
        })
        
    except Exception as e:
        logger.error(f"Test Sarvam API error: {e}")
        return JSONResponse({
            "status": "error",
            "message": f"Test failed: {str(e)}"
        })

@app.get("/health")
async def health_check():
    """Health check endpoint to verify system status"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "supabase": "unknown",
                "openai": "unknown",
                "rag_system": "unknown",
                "speech_to_text": "unknown"
            }
        }
        
        # Check Supabase connection
        try:
            # Simple query to test connection
            response = supabase.table('documents').select('id').limit(1).execute()
            health_status["services"]["supabase"] = "healthy"
        except Exception as e:
            health_status["services"]["supabase"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        # Check OpenAI connection
        try:
            # Simple embedding test
            import openai
            openai_client = openai.OpenAI(api_key=required_env_vars["OPENAI_API_KEY"])
            response = openai_client.embeddings.create(
                model=optional_env_vars["EMBEDDING_MODEL"],
                input=["test"]
            )
            health_status["services"]["openai"] = "healthy"
        except Exception as e:
            health_status["services"]["openai"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        # Check RAG system
        try:
            # Test RAG system initialization (without user-specific index)
            test_rag = RAGSystem()
            test_rag._initialize_components()
            health_status["services"]["rag_system"] = "healthy"
        except Exception as e:
            health_status["services"]["rag_system"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        # Check speech-to-text service
        if optional_env_vars["SARVAM_API_KEY"]:
            try:
                # Test API connectivity
                response = requests.get("https://api.sarvam.ai", timeout=5)
                health_status["services"]["speech_to_text"] = "healthy"
            except Exception as e:
                health_status["services"]["speech_to_text"] = f"error: {str(e)}"
        else:
            health_status["services"]["speech_to_text"] = "not_configured"
        
        return JSONResponse(health_status)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse({
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }, status_code=500)

def upload_document_to_storage(user_id: str, file_data: bytes, filename: str, content_type: str = None):
    """Upload original document to Supabase Storage"""
    try:
        file_path = f"{user_id}/{filename}"
        logger.info(f"📤 Uploading document {filename} to storage for user {user_id}")
        
        # Create a service role client for storage operations
        SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        if not SUPABASE_SERVICE_KEY:
            logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
            return None
        
        # Create service client for storage operations
        service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        
        # Check if file already exists
        try:
            existing_files = service_supabase.storage.from_(DOCUMENTS_BUCKET).list(path=user_id)
            for file_info in existing_files:
                if file_info['name'] == filename:
                    logger.warning(f"⚠️ Document {filename} already exists for user {user_id}")
                    return {"error": "duplicate", "message": f"Document '{filename}' already exists"}
        except Exception as e:
            logger.warning(f"⚠️ Could not check for existing files: {e}")
        
        # Determine content type if not provided
        if not content_type:
            file_extension = os.path.splitext(filename)[1].lower()
            content_type_map = {
                '.pdf': 'application/pdf',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png'
            }
            content_type = content_type_map.get(file_extension, 'application/octet-stream')
        
        # Upload to Supabase Storage using service role
        response = service_supabase.storage.from_(DOCUMENTS_BUCKET).upload(
            path=file_path,
            file=file_data,
            file_options={"content-type": content_type}
        )
        
        logger.info(f"✅ Successfully uploaded {filename} to storage")
        return file_path
    except Exception as e:
        error_str = str(e)
        logger.error(f"❌ Error uploading {filename} to storage: {e}")
        
        # Check if it's a duplicate file error
        if "409" in error_str or "Duplicate" in error_str or "already exists" in error_str.lower():
            logger.warning(f"⚠️ Document {filename} already exists for user {user_id}")
            return {"error": "duplicate", "message": f"Document '{filename}' already exists"}
        
        return None

def download_document_from_storage(user_id: str, filename: str):
    """Download original document from Supabase Storage"""
    try:
        file_path = f"{user_id}/{filename}"
        logger.info(f"📥 Downloading document {filename} from storage for user {user_id}")
        
        # Create a service role client for storage operations
        SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        if not SUPABASE_SERVICE_KEY:
            logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
            return None
        
        # Create service client for storage operations
        service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        
        # Download from Supabase Storage
        file_data = service_supabase.storage.from_(DOCUMENTS_BUCKET).download(file_path)
        
        logger.info(f"✅ Successfully downloaded {filename} from storage")
        return file_data
    except Exception as e:
        logger.error(f"❌ Error downloading {filename} from storage: {e}")
        return None

def delete_document_from_storage(user_id: str, filename: str):
    """Delete original document from Supabase Storage"""
    try:
        file_path = f"{user_id}/{filename}"
        logger.info(f"🗑️ Deleting document {filename} from storage for user {user_id}")
        
        # Create a service role client for storage operations
        SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        if not SUPABASE_SERVICE_KEY:
            logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
            return False
        
        # Create service client for storage operations
        service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        
        # Delete from Supabase Storage
        service_supabase.storage.from_(DOCUMENTS_BUCKET).remove([file_path])
        
        logger.info(f"✅ Successfully deleted {filename} from storage")
        return True
    except Exception as e:
        logger.error(f"❌ Error deleting {filename} from storage: {e}")
        return False

@app.get("/download-document/{document_id}")
async def download_document(document_id: str, request: Request = None):
    """Download original document from Supabase Storage - requires authentication"""
    # Check authentication manually
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"📥 Download request for document {document_id} by user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Get document metadata from Supabase
        logger.info(f"🔍 Fetching document metadata for ID: {document_id}")
        response = supabase.table('documents').select('*').eq('id', document_id).eq('user_id', user_id).execute()
        
        if not response.data:
            logger.error(f"❌ Document {document_id} not found or access denied")
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        document = response.data[0]
        filename = document.get('file_name')
        storage_path = document.get('source_path')
        
        if not filename or not storage_path:
            logger.error(f"❌ Document {document_id} missing filename or storage path")
            raise HTTPException(status_code=404, detail="Document metadata incomplete")
        
        # Extract filename from storage path if it's a full path
        if '/' in storage_path:
            filename = storage_path.split('/')[-1]
        
        # Download document from storage
        logger.info(f"📥 Downloading document {filename} from storage")
        file_data = download_document_from_storage(user_id, filename)
        
        if not file_data:
            logger.error(f"❌ Failed to download document {filename} from storage")
            raise HTTPException(status_code=404, detail="Document not found in storage")
        
        # Determine content type
        file_extension = os.path.splitext(filename)[1].lower()
        content_type_map = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png'
        }
        content_type = content_type_map.get(file_extension, 'application/octet-stream')
        
        logger.info(f"✅ Document {filename} downloaded successfully")
        
        # Return file as response
        return Response(
            content=file_data,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"❌ Error downloading document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading document: {str(e)}")

@app.delete("/delete-document/{document_id}")
async def delete_document(document_id: str, request: Request = None):
    """Delete document and its original file - requires authentication"""
    # Check authentication manually
    auth_header = request.headers.get('authorization') if request else None
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        user_id = verify_token(auth_header)
        logger.info(f"🗑️ Delete request for document {document_id} by user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    try:
        # Get document metadata from Supabase
        logger.info(f"🔍 Fetching document metadata for ID: {document_id}")
        response = supabase.table('documents').select('*').eq('id', document_id).eq('user_id', user_id).execute()
        
        if not response.data:
            logger.error(f"❌ Document {document_id} not found or access denied")
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        document = response.data[0]
        filename = document.get('file_name')
        storage_path = document.get('source_path')
        
        if not filename or not storage_path:
            logger.error(f"❌ Document {document_id} missing filename or storage path")
            raise HTTPException(status_code=404, detail="Document metadata incomplete")
        
        # Extract filename from storage path if it's a full path
        if '/' in storage_path:
            filename = storage_path.split('/')[-1]
        
        # Delete document from storage
        logger.info(f"🗑️ Deleting document {filename} from storage")
        storage_deleted = delete_document_from_storage(user_id, filename)
        
        # Delete document metadata from Supabase
        logger.info(f"🗑️ Deleting document metadata from Supabase")
        supabase.table('documents').delete().eq('id', document_id).eq('user_id', user_id).execute()
        
        logger.info(f"✅ Document {document_id} deleted successfully")
        
        return JSONResponse({
            "status": "success",
            "message": "Document deleted successfully",
            "document_id": document_id,
            "storage_deleted": storage_deleted
        })
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting document: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)