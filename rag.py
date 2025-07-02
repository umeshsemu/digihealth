import openai
import numpy as np
import faiss
import pickle
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import time
from dotenv import load_dotenv
import os
from supabase import create_client, Client
import tempfile
import io

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

class RAGSystem:
    def __init__(self, user_id: str = None):
        # ------------------ CONFIG ------------------
        # Supabase configuration
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
        
        if not self.SUPABASE_URL or not self.SUPABASE_ANON_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment variables")

        # Storage bucket configuration
        self.STORAGE_BUCKET = "user-indexes"
        self.user_id = user_id

        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4")
        self.TOP_K = int(os.getenv("TOP_K", 3))
        # --------------------------------------------

        self._initialize_components()

    def _initialize_components(self):
        """Initialize all components of the RAG system"""
        try:
            # Initialize OpenAI client
            logger.info("🤖 Initializing OpenAI client...")
            if not self.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not found in environment variables")
            self.openai_client = openai.OpenAI(api_key=self.OPENAI_API_KEY)
            
            # Initialize Supabase client
            logger.info("🔗 Initializing Supabase client...")
            self.supabase = create_client(self.SUPABASE_URL, self.SUPABASE_ANON_KEY)
            
            # Initialize index and doc_ids as None
            self.index = None
            self.doc_ids = []
            
            logger.info("✅ RAG system initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Error initializing RAG system: {e}")
            raise

    def load_user_index(self, user_id: str) -> bool:
        """Load user-specific index from Supabase Storage"""
        try:
            logger.info(f"📥 Loading index for user: {user_id}")
            
            # Create a service role client for storage operations
            SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
            if not SUPABASE_SERVICE_KEY:
                logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
                return False
            
            # Create service client for storage operations
            service_supabase = create_client(self.SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Download FAISS index from storage
            temp_idx_path = None
            temp_pkl_path = None
            
            try:
                faiss_path = f"{user_id}/faiss_index.idx"
                logger.info(f"📥 Downloading FAISS index from {faiss_path}")
                
                faiss_data = service_supabase.storage.from_(self.STORAGE_BUCKET).download(faiss_path)
                
                # Save to temporary file and load
                with tempfile.NamedTemporaryFile(suffix='.idx', delete=False) as temp_idx:
                    temp_idx_path = temp_idx.name
                    temp_idx.write(faiss_data)
                    temp_idx.flush()
                
                # Load the index after writing
                self.index = faiss.read_index(temp_idx_path)
                logger.info("✅ FAISS index loaded successfully")
                
            except Exception as e:
                logger.error(f"❌ Error loading FAISS index: {e}")
                return False
            
            # Download ID map from storage
            try:
                id_map_path = f"{user_id}/id_map.pkl"
                logger.info(f"📥 Downloading ID map from {id_map_path}")
                
                id_map_data = service_supabase.storage.from_(self.STORAGE_BUCKET).download(id_map_path)
                
                # Load pickle data
                self.doc_ids = pickle.loads(id_map_data)
                
                logger.info(f"✅ ID map loaded successfully with {len(self.doc_ids)} document IDs")
                
            except Exception as e:
                logger.error(f"❌ Error loading ID map: {e}")
                return False
            
            logger.info(f"✅ Successfully loaded index for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error loading user index: {e}")
            return False
        finally:
            # Clean up temporary files with proper error handling
            if temp_idx_path and os.path.exists(temp_idx_path):
                try:
                    os.unlink(temp_idx_path)
                    logger.info("🧹 Temporary FAISS index file cleaned up")
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete temporary FAISS index file: {e}")
            
            if temp_pkl_path and os.path.exists(temp_pkl_path):
                try:
                    os.unlink(temp_pkl_path)
                    logger.info("🧹 Temporary ID map file cleaned up")
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete temporary ID map file: {e}")

    def check_user_has_index(self, user_id: str) -> bool:
        """Check if user has an index in storage"""
        try:
            # Create a service role client for storage operations
            SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
            if not SUPABASE_SERVICE_KEY:
                logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
                return False
            
            # Create service client for storage operations
            service_supabase = create_client(self.SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            files = service_supabase.storage.from_(self.STORAGE_BUCKET).list(path=user_id)
            has_faiss = any(file['name'] == 'faiss_index.idx' for file in files)
            has_id_map = any(file['name'] == 'id_map.pkl' for file in files)
            return has_faiss and has_id_map
        except Exception as e:
            logger.error(f"❌ Error checking user index: {e}")
            return False

    def get_query_embedding(self, text: str) -> np.ndarray:
        """Get embedding for a query text"""
        try:
            logger.info("🔍 Generating query embedding...")
            response = self.openai_client.embeddings.create(
                model=self.EMBEDDING_MODEL,
                input=[text]
            )
            embedding = np.array(response.data[0].embedding, dtype="float32")
            logger.info("✅ Query embedding generated successfully")
            return embedding
        except Exception as e:
            logger.error(f"❌ Error getting query embedding: {e}")
            raise

    def search_documents(self, query: str, user_id: str = None) -> List[Dict[str, Any]]:
        """Search for relevant documents using the query"""
        try:
            logger.info(f"🔍 Searching documents for user: {user_id}")
            
            # Load user index if not already loaded
            if self.index is None and user_id:
                if not self.load_user_index(user_id):
                    logger.error(f"❌ Failed to load index for user {user_id}")
                    return []
            
            if self.index is None:
                logger.error("❌ No index available for search")
                return []
            
            # Get query embedding
            query_vector = self.get_query_embedding(query).reshape(1, -1)
            
            # Search FAISS index
            logger.info("🔍 Performing vector search with FAISS...")
            D, I = self.index.search(query_vector, self.TOP_K)
            
            # Get top-k document IDs using ID map
            top_doc_ids = [self.doc_ids[i] for i in I[0]]
            logger.info(f"📄 Found {len(top_doc_ids)} relevant documents")
            
            # Fetch documents from Supabase
            logger.info("📊 Fetching documents from Supabase...")
            try:
                response = self.supabase.table('documents').select('*').in_('id', top_doc_ids).execute()
                all_docs = response.data
                
                # Filter by user_id if provided
                if user_id:
                    all_docs = [doc for doc in all_docs if doc.get('user_id') == user_id]
                    logger.info(f"🔒 Filtered to {len(all_docs)} user-specific documents")
                
                # Add similarity scores to documents
                top_docs = []
                for doc in all_docs:
                    if doc['id'] in top_doc_ids:
                        idx = top_doc_ids.index(doc['id'])
                        distance = float(D[0][idx])
                        
                        # Convert distance to similarity percentage
                        # FAISS L2 distance: lower = more similar
                        # Convert to similarity: 1 / (1 + distance) gives 0-1 range
                        # Then multiply by 100 for percentage
                        similarity_score = 1 / (1 + distance) * 100
                        
                        doc['similarity_score'] = similarity_score
                        top_docs.append(doc)
                
                logger.info(f"✅ Retrieved {len(top_docs)} documents with similarity scores")
                return top_docs
                
            except Exception as e:
                logger.error(f"❌ Error fetching documents from Supabase: {e}")
                raise
            
        except Exception as e:
            logger.error(f"❌ Error searching documents: {e}")
            raise

    def generate_response(self, query: str, context_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate a response using GPT based on the query and context"""
        try:
            logger.info("🤖 Generating response with GPT...")
            
            # Format context
            context = "\n\n".join([doc.get("summary", "") for doc in context_docs])
            
            # Build GPT prompt
            prompt = f"""Use the following summaries to answer the question. If the information is not available in the summaries, say so.

Summaries:
{context}

Question: {query}
Answer:"""
            
            # Generate response
            response = self.openai_client.chat.completions.create(
                model=self.GPT_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            result = {
                "answer": response.choices[0].message.content,
                "sources": [
                    {
                        "document_id": str(doc["id"]),
                        "filename": doc.get("file_name", "Unknown"),
                        "similarity_score": doc["similarity_score"],
                        "summary": doc.get("summary", "")
                    }
                    for doc in context_docs
                ]
            }
            
            logger.info("✅ Response generated successfully")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error generating response: {e}")
            raise

    def process_query(self, query: str, user_id: str = None) -> Dict[str, Any]:
        """Process a query through the entire RAG pipeline"""
        try:
            start_time = time.time()
            logger.info(f"🚀 Starting RAG pipeline for query: '{query[:50]}...'")
            
            # Check if user has an index
            if user_id and not self.check_user_has_index(user_id):
                logger.warning(f"⚠️ No index found for user {user_id}")
                return {
                    "answer": "No documents have been indexed yet. Please upload and index some documents first.",
                    "sources": [],
                    "processing_time": time.time() - start_time
                }
            
            # Search for relevant documents
            relevant_docs = self.search_documents(query, user_id)
            
            if not relevant_docs:
                logger.warning("⚠️ No relevant documents found")
                return {
                    "answer": "I couldn't find any relevant documents to answer your question. Please try rephrasing your query or upload more documents.",
                    "sources": [],
                    "processing_time": time.time() - start_time
                }
            
            # Generate response
            result = self.generate_response(query, relevant_docs)
            
            # Add processing time
            result["processing_time"] = time.time() - start_time
            logger.info(f"✅ RAG pipeline completed in {result['processing_time']:.2f} seconds")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing query: {e}")
            raise

# For command-line usage
if __name__ == "__main__":
    try:
        rag = RAGSystem()
        user_query = input("Enter your query: ")
        user_id = input("Enter user ID (optional): ").strip() or None
        
        if user_id:
            if not rag.load_user_index(user_id):
                print("❌ Failed to load user index")
                exit(1)
        
        result = rag.process_query(user_query, user_id)
        
        print("\n🔎 Answer:\n")
        print(result["answer"])
        print("\nSources:")
        for source in result["sources"]:
            print(f"\nDocument ID: {source['document_id']}")
            print(f"Similarity Score: {source['similarity_score']:.4f}")
            print(f"Summary: {source['summary'][:200]}...")
        
    except Exception as e:
        logger.error(f"❌ Error in main: {e}")
        raise