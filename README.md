# DigiHealth - AI-Powered Healthcare Document Processing

A modern web app for secure healthcare document upload, AI-powered text extraction, semantic search, and speech-to-text, with user authentication via Supabase.

---

## Features

- **Document Upload & Storage**: Upload healthcare documents (PDF, images) and store securely in Supabase.
- **AI Text Extraction**: Extract and summarize text using Google Gemini and OpenAI.
- **Semantic Search**: Retrieve relevant information from your documents using RAG (Retrieval-Augmented Generation).
- **Speech-to-Text**: Record audio in-browser, transcribe with Sarvam AI.
- **User Authentication**: Secure sign-up, login, and JWT-based API protection via Supabase.
- **Mobile-Optimized UI**: Responsive, modern frontend.

---

## 1. Environment Variables

Create a `.env` file in your project root with the following content:

```env
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_key

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
EMBEDDING_MODEL=text-embedding-3-small
GPT_MODEL=gpt-4

# Google Gemini Configuration
GEMINI_API_KEY=your_gemini_api_key

# Sarvam AI Configuration (for Speech-to-Text)
SARVAM_API_KEY=your_sarvam_api_key
```

**How to get these:**
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`: From your Supabase project dashboard (see below).
- `OPENAI_API_KEY`: From your [OpenAI account](https://platform.openai.com/account/api-keys).
- `GEMINI_API_KEY`: From your [Google AI Studio](https://aistudio.google.com/app/apikey).
- `SARVAM_API_KEY`: Sign up at [Sarvam AI](https://sarvam.ai) and generate an API key.

---

## 2. Supabase Setup

### a. Create a Supabase Account & Project

1. Go to [supabase.com](https://supabase.com) and sign up.
2. Create a new project (choose a strong password and a region close to you).
3. In your project dashboard, go to **Settings > API** to find your `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
4. Go to **Settings > Service Role** to get your `SUPABASE_SERVICE_KEY` (keep this secret).

### b. Enable Authentication

- Go to **Authentication > Settings** and enable **Email** sign-in.

### c. Create the Database Table

In the **SQL Editor** in Supabase, run the following SQL:

```sql
-- Enable pgvector extension for embeddings
create extension if not exists vector;

create table documents (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid references auth.users(id) on delete cascade,
    file_name text not null,
    summary text,
    source_path text,
    embedding vector(1536), 
    timestamp timestamptz default now(),
    indexed_at timestamptz
);

create index documents_user_id_idx on documents(user_id);
```
-- =====================================================
-- Supabase Storage Bucket Setup for User-Specific Indexes
-- =====================================================

-- Step 1: Create the storage bucket for user indexes
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'user-indexes',
    'user-indexes',
    false, -- Private bucket for security
    104857600, -- 100MB file size limit
    ARRAY['application/octet-stream', 'application/x-binary'] -- Allow binary files
) ON CONFLICT (id) DO NOTHING;

-- Step 2: Create RLS (Row Level Security) policy for the bucket
-- This ensures only authenticated users can access their own indexes
CREATE POLICY "Users can access their own indexes" ON storage.objects
    FOR ALL USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 3: Create policy for inserting user indexes
CREATE POLICY "Users can upload their own indexes" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 4: Create policy for updating user indexes
CREATE POLICY "Users can update their own indexes" ON storage.objects
    FOR UPDATE USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 5: Create policy for deleting user indexes
CREATE POLICY "Users can delete their own indexes" ON storage.objects
    FOR DELETE USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 6: Create a function to get user's index file path
CREATE OR REPLACE FUNCTION get_user_index_path(user_uuid text, filename text)
RETURNS text AS $$
BEGIN
    RETURN user_uuid || '/' || filename;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 7: Create a function to check if user has indexes
CREATE OR REPLACE FUNCTION user_has_indexes(user_uuid text)
RETURNS boolean AS $$
DECLARE
    index_count integer;
BEGIN
    SELECT COUNT(*) INTO index_count
    FROM storage.objects
    WHERE bucket_id = 'user-indexes'
    AND split_part(name, '/', 1) = user_uuid;
    
    RETURN index_count > 0;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 8: Create a function to list user's index files
CREATE OR REPLACE FUNCTION list_user_indexes(user_uuid text)
RETURNS TABLE(filename text, size bigint, created_at timestamptz) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        split_part(o.name, '/', 2) as filename,
        (o.metadata->>'size')::bigint as size,
        o.created_at
    FROM storage.objects o
    WHERE o.bucket_id = 'user-indexes'
    AND split_part(o.name, '/', 1) = user_uuid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 9: Create a function to delete all user indexes
CREATE OR REPLACE FUNCTION delete_user_indexes(user_uuid text)
RETURNS integer AS $$
DECLARE
    deleted_count integer;
BEGIN
    DELETE FROM storage.objects
    WHERE bucket_id = 'user-indexes'
    AND split_part(name, '/', 1) = user_uuid;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 10: Grant necessary permissions to authenticated users
GRANT USAGE ON SCHEMA storage TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects TO authenticated;
GRANT EXECUTE ON FUNCTION get_user_index_path(text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION user_has_indexes(text) TO authenticated;
GRANT EXECUTE ON FUNCTION list_user_indexes(text) TO authenticated;
GRANT EXECUTE ON FUNCTION delete_user_indexes(text) TO authenticated;

-- Step 11: Create a view for easy access to user index information
CREATE OR REPLACE VIEW user_index_info AS
SELECT 
    auth.uid() as user_id,
    split_part(o.name, '/', 1) as user_uuid,
    split_part(o.name, '/', 2) as filename,
    o.metadata->>'size' as file_size,
    o.created_at,
    o.updated_at
FROM storage.objects o
WHERE o.bucket_id = 'user-indexes'
AND auth.uid()::text = split_part(o.name, '/', 1);

-- Grant access to the view
GRANT SELECT ON user_index_info TO authenticated;

-- =====================================================
-- Verification Queries (run these to verify setup)
-- =====================================================

-- Check if bucket was created
-- SELECT * FROM storage.buckets WHERE id = 'user-indexes';

-- Check if policies were created
-- SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual 
-- FROM pg_policies 
-- WHERE tablename = 'objects' AND schemaname = 'storage';

-- Check if functions were created
-- SELECT routine_name, routine_type 
-- FROM information_schema.routines 
-- WHERE routine_schema = 'public' 
-- AND routine_name LIKE '%index%';

-- =====================================================
-- Usage Examples (for reference)
-- =====================================================

/*
-- Upload a user's index file (from your application)
-- INSERT INTO storage.objects (bucket_id, name, owner, metadata)
-- VALUES ('user-indexes', 'user-uuid-here/faiss_index.idx', auth.uid(), '{"size": 12345}'::jsonb);

-- Download a user's index file (from your application)
-- SELECT * FROM storage.objects 
-- WHERE bucket_id = 'user-indexes' 
-- AND name = 'user-uuid-here/faiss_index.idx';

-- List all files for a user
-- SELECT * FROM list_user_indexes('user-uuid-here');

-- Check if user has any indexes
-- SELECT user_has_indexes('user-uuid-here');

-- Delete all indexes for a user
-- SELECT delete_user_indexes('user-uuid-here');
*/

-- =====================================================
-- Setup Complete!
-- ===================================================== 
-- =====================================================
-- Supabase Storage Bucket Setup for User-Specific Indexes
-- =====================================================

-- Step 1: Create the storage bucket for user indexes
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'user-indexes',
    'user-indexes',
    false, -- Private bucket for security
    104857600, -- 100MB file size limit
    ARRAY['application/octet-stream', 'application/x-binary'] -- Allow binary files
) ON CONFLICT (id) DO NOTHING;

-- Step 2: Create RLS (Row Level Security) policy for the bucket
-- This ensures only authenticated users can access their own indexes
CREATE POLICY "Users can access their own indexes" ON storage.objects
    FOR ALL USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 3: Create policy for inserting user indexes
CREATE POLICY "Users can upload their own indexes" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 4: Create policy for updating user indexes
CREATE POLICY "Users can update their own indexes" ON storage.objects
    FOR UPDATE USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 5: Create policy for deleting user indexes
CREATE POLICY "Users can delete their own indexes" ON storage.objects
    FOR DELETE USING (
        bucket_id = 'user-indexes' 
        AND auth.uid()::text = split_part(name, '/', 1)
    );

-- Step 6: Create a function to get user's index file path
CREATE OR REPLACE FUNCTION get_user_index_path(user_uuid text, filename text)
RETURNS text AS $$
BEGIN
    RETURN user_uuid || '/' || filename;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 7: Create a function to check if user has indexes
CREATE OR REPLACE FUNCTION user_has_indexes(user_uuid text)
RETURNS boolean AS $$
DECLARE
    index_count integer;
BEGIN
    SELECT COUNT(*) INTO index_count
    FROM storage.objects
    WHERE bucket_id = 'user-indexes'
    AND split_part(name, '/', 1) = user_uuid;
    
    RETURN index_count > 0;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 8: Create a function to list user's index files
CREATE OR REPLACE FUNCTION list_user_indexes(user_uuid text)
RETURNS TABLE(filename text, size bigint, created_at timestamptz) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        split_part(o.name, '/', 2) as filename,
        (o.metadata->>'size')::bigint as size,
        o.created_at
    FROM storage.objects o
    WHERE o.bucket_id = 'user-indexes'
    AND split_part(o.name, '/', 1) = user_uuid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 9: Create a function to delete all user indexes
CREATE OR REPLACE FUNCTION delete_user_indexes(user_uuid text)
RETURNS integer AS $$
DECLARE
    deleted_count integer;
BEGIN
    DELETE FROM storage.objects
    WHERE bucket_id = 'user-indexes'
    AND split_part(name, '/', 1) = user_uuid;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Step 10: Grant necessary permissions to authenticated users
GRANT USAGE ON SCHEMA storage TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects TO authenticated;
GRANT EXECUTE ON FUNCTION get_user_index_path(text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION user_has_indexes(text) TO authenticated;
GRANT EXECUTE ON FUNCTION list_user_indexes(text) TO authenticated;
GRANT EXECUTE ON FUNCTION delete_user_indexes(text) TO authenticated;

-- Step 11: Create a view for easy access to user index information
CREATE OR REPLACE VIEW user_index_info AS
SELECT 
    auth.uid() as user_id,
    split_part(o.name, '/', 1) as user_uuid,
    split_part(o.name, '/', 2) as filename,
    o.metadata->>'size' as file_size,
    o.created_at,
    o.updated_at
FROM storage.objects o
WHERE o.bucket_id = 'user-indexes'
AND auth.uid()::text = split_part(o.name, '/', 1);

-- Grant access to the view
GRANT SELECT ON user_index_info TO authenticated;

-- =====================================================
-- Verification Queries (run these to verify setup)
-- =====================================================

-- Check if bucket was created
-- SELECT * FROM storage.buckets WHERE id = 'user-indexes';

-- Check if policies were created
-- SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual 
-- FROM pg_policies 
-- WHERE tablename = 'objects' AND schemaname = 'storage';

-- Check if functions were created
-- SELECT routine_name, routine_type 
-- FROM information_schema.routines 
-- WHERE routine_schema = 'public' 
-- AND routine_name LIKE '%index%';

-- =====================================================
-- Usage Examples (for reference)
-- =====================================================

/*
-- Upload a user's index file (from your application)
-- INSERT INTO storage.objects (bucket_id, name, owner, metadata)
-- VALUES ('user-indexes', 'user-uuid-here/faiss_index.idx', auth.uid(), '{"size": 12345}'::jsonb);

-- Download a user's index file (from your application)
-- SELECT * FROM storage.objects 
-- WHERE bucket_id = 'user-indexes' 
-- AND name = 'user-uuid-here/faiss_index.idx';

-- List all files for a user
-- SELECT * FROM list_user_indexes('user-uuid-here');

-- Check if user has any indexes
-- SELECT user_has_indexes('user-uuid-here');

-- Delete all indexes for a user
-- SELECT delete_user_indexes('user-uuid-here');
*/

-- =====================================================
-- Setup Complete!
-- ===================================================== 
---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Run the Application

```bash
uvicorn main:app --reload
```

- Visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## 5. API Endpoints

### Public Routes

- `GET /` — Homepage
- `POST /auth/signup` — User registration
- `POST /auth/login` — User login
- `POST /auth/logout` — User logout
- `GET /auth/verify` — Verify authentication status

### Protected Routes (Require JWT)

- `GET /upload` — Upload page
- `POST /upload-file` — File upload and processing
- `GET /index` — Indexing dashboard
- `POST /speech-to-text` — Audio transcription (Sarvam AI)
- ...and more (see `main.py` for full list)


## 6. Useful Links
- [Supabase Docs](https://supabase.com/docs)
- [OpenAI API](https://platform.openai.com/docs/api-reference)
- [Google Gemini API](https://ai.google.dev/)
- [Sarvam AI](https://sarvam.ai)

