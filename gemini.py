import os
import fitz  # PyMuPDF
import google.generativeai as genai
from datetime import datetime
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

def extract_images_from_pdf(pdf_path, dpi=300):
    """
    Converts each page of a PDF into JPEG image bytes.
    """
    logger.info(f"📄 Extracting images from PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    images = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        image_bytes = pix.tobytes("jpeg")
        images.append((image_bytes, f"page_{i + 1}"))
    logger.info(f"✅ Extracted {len(images)} pages from PDF")
    return images


def read_image_file(image_path):
    """
    Reads a single image file and returns its bytes.
    """
    logger.info(f"🖼️ Reading image file: {image_path}")
    with open(image_path, "rb") as img:
        image_data = [(img.read(), os.path.basename(image_path))]
    logger.info(f"✅ Image file read successfully")
    return image_data


def extract_text_summary_from_images(images_with_labels, prompt="Extract the text and summarize the file."):
    """
    Uses Gemini Flash 2.0 to extract and summarize text from a list of image byte data.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("❌ GEMINI_API_KEY not found in environment variables")
        raise EnvironmentError("GEMINI_API_KEY not found in environment variables.")

    logger.info("🤖 Initializing Gemini client...")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    all_results = []
    logger.info(f"🔄 Processing {len(images_with_labels)} images with Gemini...")

    for i, (image_bytes, label) in enumerate(images_with_labels):
        logger.info(f"📝 Processing {label} ({i+1}/{len(images_with_labels)})...")
        
        try:
            # Create image part
            image_part = {
                "mime_type": "image/jpeg",
                "data": image_bytes
            }
            
            # Generate content with image and prompt
            response = model.generate_content([prompt, image_part])
            response_text = response.text
            
            all_results.append(f"\n--- 📄 {label} ---\n{response_text.strip()}")
            logger.info(f"✅ {label} processed successfully")
        except Exception as e:
            logger.error(f"❌ Error processing {label}: {e}")
            all_results.append(f"\n--- 📄 {label} ---\nError processing this page: {str(e)}")

    final_result = "\n".join(all_results)
    logger.info(f"✅ All images processed. Total summary length: {len(final_result)} characters")
    return final_result


def process_file(file_path):
    logger.info(f"🚀 Starting file processing: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        logger.info("📄 Processing PDF file...")
        images = extract_images_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png"]:
        logger.info("🖼️ Processing image file...")
        images = read_image_file(file_path)
    else:
        logger.error(f"❌ Unsupported file type: {ext}")
        raise ValueError("Unsupported file type. Use PDF or image.")
    
    logger.info("🤖 Starting AI text extraction...")
    summary = extract_text_summary_from_images(images)
    logger.info("✅ File processing completed successfully")
    return summary

def save_summary_to_supabase(summary_text, source_file, user_id=None, supabase_client=None, storage_path=None):
    """
    Saves the summary text into Supabase documents table with user_id and storage path.
    """
    if not supabase_client:
        logger.error("❌ Supabase client not provided")
        raise ValueError("Supabase client is required")
    
    logger.info(f"💾 Saving document to Supabase for user: {user_id}")
    logger.info(f"📄 File: {source_file}")
    logger.info(f"📝 Summary length: {len(summary_text)} characters")
    if storage_path:
        logger.info(f"📁 Storage path: {storage_path}")
    
    try:
        # Prepare document data
        doc_data = {
            "user_id": user_id,
            "file_name": os.path.basename(source_file),
            "summary": summary_text,
            "source_path": storage_path if storage_path else source_file,  # Use storage path if available
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Insert document into Supabase
        response = supabase_client.table('documents').insert(doc_data).execute()
        
        if response.data:
            document_id = response.data[0]['id']
            logger.info(f"✅ Document saved successfully with ID: {document_id}")
            return document_id
        else:
            logger.error("❌ No data returned from Supabase insert")
            raise Exception("Failed to save document to Supabase")
            
    except Exception as e:
        logger.error(f"❌ Error saving to Supabase: {e}")
        raise Exception(f"Failed to save document to Supabase: {str(e)}")

if __name__ == "__main__":
    # 🧪 Example: Replace this with your actual file
    #file_path = r"C:\Users\umesh\Downloads\WhatsApp Image 2025-05-27 at 9.17.44 PM.jpeg"# or "sample_image.jpg"
    file_path = r"C:\Users\umesh\Downloads\OIP.jpg"
    summary = process_file(file_path)
    print(summary)
    # Note: save_summary_to_supabase requires a supabase client, so it's not called here in the test