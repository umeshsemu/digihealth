import openai
import time
import numpy as np
import faiss
import pickle
import os
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
import tempfile
import io

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment variables")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
logger.info("✅ Supabase client initialized for indexing")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Storage bucket configuration
STORAGE_BUCKET = "user-indexes"

def upload_index_to_storage(user_id: str, index_data: bytes, filename: str):
    """Upload index file to Supabase Storage"""
    try:
        file_path = f"{user_id}/{filename}"
        logger.info(f"📤 Uploading {filename} to storage for user {user_id}")
        
        # Create a service role client for storage operations
        SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        if not SUPABASE_SERVICE_KEY:
            logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
            return False
        
        # Create service client for storage operations
        service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        
        # Upload to Supabase Storage using service role
        response = service_supabase.storage.from_(STORAGE_BUCKET).upload(
            path=file_path,
            file=index_data,
            file_options={"content-type": "application/octet-stream"}
        )
        
        logger.info(f"✅ Successfully uploaded {filename} to storage")
        return True
    except Exception as e:
        logger.error(f"❌ Error uploading {filename} to storage: {e}")
        return False

def delete_user_indexes_from_storage(user_id: str):
    """Delete all index files for a user from storage"""
    try:
        logger.info(f"🗑️ Deleting all indexes for user {user_id} from storage")
        
        # Create a service role client for storage operations
        SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
        if not SUPABASE_SERVICE_KEY:
            logger.error("❌ SUPABASE_SERVICE_KEY not found in environment variables")
            return False
        
        # Create service client for storage operations
        service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        
        # List all files for the user
        files = service_supabase.storage.from_(STORAGE_BUCKET).list(path=user_id)
        
        if files:
            # Delete each file
            for file_info in files:
                file_path = f"{user_id}/{file_info['name']}"
                service_supabase.storage.from_(STORAGE_BUCKET).remove([file_path])
                logger.info(f"🗑️ Deleted {file_path}")
        
        logger.info(f"✅ Successfully deleted all indexes for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error deleting indexes for user {user_id}: {e}")
        return False

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Index documents for RAG system')
    parser.add_argument('--user-id', type=str, required=True, help='User ID to index documents for')
    parser.add_argument('--force-rebuild', action='store_true', help='Force rebuild the entire index (fixes UUID mismatch)')
    args = parser.parse_args()
    
    # If force rebuild is requested, do that instead
    if args.force_rebuild:
        logger.info("🔄 Force rebuild requested...")
        force_rebuild_index(args.user_id)
        return
    
    logger.info(f"🚀 Starting indexing process for user: {args.user_id}")
    
    try:
        # Initialize OpenAI client
        logger.info("🤖 Initializing OpenAI client...")
        openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

        # Delete existing user indexes from storage
        delete_user_indexes_from_storage(args.user_id)

        # Step 1: Get documents without embeddings from Supabase for this user
        logger.info("📊 Fetching documents without embeddings from Supabase...")
        
        try:
            # Build query for documents without embeddings for specific user
            query = supabase.table('documents').select('*').is_('embedding', 'null').eq('user_id', args.user_id)
            response = query.execute()
            documents_to_embed = response.data
            logger.info(f"📄 Found {len(documents_to_embed)} documents to embed for user {args.user_id}...")
        except Exception as e:
            logger.error(f"❌ Error fetching documents from Supabase: {e}")
            raise

        # Step 2: Generate embeddings for documents without them
        for i, doc in enumerate(documents_to_embed):
            summary = doc.get("summary")
            if not summary:
                logger.warning(f"⚠️ Skipping document {doc['id']} - no summary field.")
                continue

            logger.info(f"🔄 Processing document {i+1}/{len(documents_to_embed)}: {doc.get('file_name', 'Unknown')}")

            try:
                # Generate embedding
                response = openai_client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=summary
                )
                embedding = response.data[0].embedding

                # Update document in Supabase with embedding
                supabase.table('documents').update({
                    'embedding': embedding
                }).eq('id', doc['id']).execute()

                logger.info(f"✅ Embedded and updated document {doc['id']}")

            except Exception as e:
                logger.error(f"❌ Error processing document {doc['id']}: {e}")
                time.sleep(5)  # Wait before next attempt

        # Step 3: Load all documents with embeddings from Supabase for this user
        logger.info("📊 Loading all documents with embeddings from Supabase...")
        
        try:
            # Build query for documents with embeddings for specific user
            query = supabase.table('documents').select('*').not_.is_('embedding', 'null').eq('user_id', args.user_id)
            response = query.execute()
            documents = response.data
            logger.info(f"📄 Loaded {len(documents)} documents with embeddings for user {args.user_id}.")
        except Exception as e:
            logger.error(f"❌ Error loading documents with embeddings: {e}")
            raise

        if not documents:
            logger.error("❌ No embeddings found to build FAISS index.")
            raise Exception("No embeddings found to build FAISS index.")

        # Step 4: Prepare data for FAISS
        logger.info("🔧 Preparing data for FAISS index...")
        
        # Convert embeddings to proper format
        processed_embeddings = []
        for doc in documents:
            embedding_data = doc["embedding"]
            
            # Handle different embedding data types
            if isinstance(embedding_data, str):
                # If it's a string, try to evaluate it as a list
                try:
                    import ast
                    embedding_list = ast.literal_eval(embedding_data)
                    processed_embeddings.append(embedding_list)
                    logger.info(f"✅ Converted string embedding to list for document {doc['id']}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse embedding string for document {doc['id']}: {e}")
                    continue
            elif isinstance(embedding_data, list):
                # If it's already a list, use it directly
                processed_embeddings.append(embedding_data)
            else:
                logger.error(f"❌ Unknown embedding data type for document {doc['id']}: {type(embedding_data)}")
                continue
        
        if not processed_embeddings:
            logger.error("❌ No valid embeddings found to build FAISS index.")
            raise Exception("No valid embeddings found to build FAISS index.")
        
        # Convert to numpy array
        embeddings = np.array(processed_embeddings).astype("float32")
        
        # Get doc_ids that correspond to the processed embeddings
        doc_ids = []
        for doc in documents:
            embedding_data = doc["embedding"]
            if isinstance(embedding_data, str):
                try:
                    import ast
                    ast.literal_eval(embedding_data)  # Test if it can be parsed
                    doc_ids.append(str(doc["id"]))
                except:
                    continue
            elif isinstance(embedding_data, list):
                doc_ids.append(str(doc["id"]))
        
        logger.info(f"✅ Prepared {len(embeddings)} embeddings with shape {embeddings.shape}")
        logger.info(f"✅ Matched {len(doc_ids)} document IDs")

        # Step 5: Build new FAISS index
        logger.info("🏗️ Building new FAISS index...")
        embedding_dim = embeddings.shape[1]
        index = faiss.IndexFlatL2(embedding_dim)
        index.add(embeddings)

        # Step 6: Save index and map to temporary files, then upload to storage
        logger.info("💾 Saving FAISS index to storage...")
        
        # Save FAISS index to bytes
        temp_idx_path = None
        temp_pkl_path = None
        
        try:
            with tempfile.NamedTemporaryFile(suffix='.idx', delete=False) as temp_idx:
                temp_idx_path = temp_idx.name
                faiss.write_index(index, temp_idx_path)
            
            # Read the file after writing
            with open(temp_idx_path, 'rb') as f:
                index_data = f.read()
            
            # Save ID map to bytes
            with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as temp_pkl:
                temp_pkl_path = temp_pkl.name
                with open(temp_pkl_path, 'wb') as f:
                    pickle.dump(doc_ids, f)
            
            # Read the pickle file after writing
            with open(temp_pkl_path, 'rb') as f:
                id_map_data = f.read()
            
            # Upload to Supabase Storage
            if upload_index_to_storage(args.user_id, index_data, "faiss_index.idx"):
                logger.info(f"✅ FAISS index uploaded to storage for user {args.user_id}")
            else:
                raise Exception("Failed to upload FAISS index to storage")
            
            if upload_index_to_storage(args.user_id, id_map_data, "id_map.pkl"):
                logger.info(f"✅ ID map uploaded to storage for user {args.user_id}")
            else:
                raise Exception("Failed to upload ID map to storage")
                
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

        # Step 7: Update indexed_at timestamp for all processed documents
        logger.info("🕒 Updating indexed_at timestamps...")
        try:
            # Build update query for documents with embeddings for specific user
            update_query = supabase.table('documents').update({
                'indexed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ')
            }).not_.is_('embedding', 'null').eq('user_id', args.user_id)
            
            update_query.execute()
            logger.info("✅ Indexed timestamps updated successfully")
        except Exception as e:
            logger.warning(f"⚠️ Could not update indexed timestamps: {e}")

        logger.info("🎉 Indexing completed successfully!")
        return True

    except Exception as e:
        logger.error(f"❌ Error during indexing: {e}")
        raise

def force_rebuild_index(user_id: str):
    """Force rebuild the FAISS index and ID map to ensure correct UUIDs"""
    logger.info(f"🔄 Force rebuilding FAISS index and ID map for user {user_id}...")
    
    try:
        # Delete existing user indexes from storage
        delete_user_indexes_from_storage(user_id)
        
        # Get all documents with embeddings from Supabase for this user
        logger.info("📊 Fetching all documents with embeddings from Supabase...")
        response = supabase.table('documents').select('*').not_.is_('embedding', 'null').eq('user_id', user_id).execute()
        documents = response.data
        logger.info(f"📄 Found {len(documents)} documents with embeddings for user {user_id}")
        
        if not documents:
            logger.error("❌ No documents with embeddings found")
            return False
        
        # Process embeddings
        processed_embeddings = []
        doc_ids = []
        
        for doc in documents:
            embedding_data = doc["embedding"]
            
            # Handle different embedding data types
            if isinstance(embedding_data, str):
                try:
                    import ast
                    embedding_list = ast.literal_eval(embedding_data)
                    processed_embeddings.append(embedding_list)
                    doc_ids.append(str(doc["id"]))
                    logger.info(f"✅ Processed string embedding for document {doc['id']}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse embedding for document {doc['id']}: {e}")
                    continue
            elif isinstance(embedding_data, list):
                processed_embeddings.append(embedding_data)
                doc_ids.append(str(doc["id"]))
                logger.info(f"✅ Processed array embedding for document {doc['id']}")
            else:
                logger.error(f"❌ Unknown embedding type for document {doc['id']}: {type(embedding_data)}")
                continue
        
        if not processed_embeddings:
            logger.error("❌ No valid embeddings found")
            return False
        
        # Convert to numpy array
        embeddings = np.array(processed_embeddings).astype("float32")
        logger.info(f"✅ Prepared {len(embeddings)} embeddings with shape {embeddings.shape}")
        logger.info(f"✅ Matched {len(doc_ids)} document IDs")
        
        # Build new FAISS index
        logger.info("🏗️ Building new FAISS index...")
        embedding_dim = embeddings.shape[1]
        index = faiss.IndexFlatL2(embedding_dim)
        index.add(embeddings)

        # Save index and map to temporary files, then upload to storage
        logger.info("💾 Saving new FAISS index to storage...")
        
        # Save FAISS index to bytes
        temp_idx_path = None
        temp_pkl_path = None
        
        try:
            with tempfile.NamedTemporaryFile(suffix='.idx', delete=False) as temp_idx:
                temp_idx_path = temp_idx.name
                faiss.write_index(index, temp_idx_path)
            
            # Read the file after writing
            with open(temp_idx_path, 'rb') as f:
                index_data = f.read()
            
            # Save ID map to bytes
            with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as temp_pkl:
                temp_pkl_path = temp_pkl.name
                with open(temp_pkl_path, 'wb') as f:
                    pickle.dump(doc_ids, f)
            
            # Read the pickle file after writing
            with open(temp_pkl_path, 'rb') as f:
                id_map_data = f.read()
            
            # Upload to Supabase Storage
            if upload_index_to_storage(user_id, index_data, "faiss_index.idx"):
                logger.info(f"✅ FAISS index uploaded to storage for user {user_id}")
            else:
                raise Exception("Failed to upload FAISS index to storage")
            
            if upload_index_to_storage(user_id, id_map_data, "id_map.pkl"):
                logger.info(f"✅ ID map uploaded to storage for user {user_id}")
            else:
                raise Exception("Failed to upload ID map to storage")
                
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

        logger.info("🎉 Force rebuild completed successfully!")
        return True

    except Exception as e:
        logger.error(f"❌ Error during force rebuild: {e}")
        raise

if __name__ == "__main__":
    main()
