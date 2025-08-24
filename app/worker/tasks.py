import os
from typing import Dict, Any, List
from uuid import UUID
import base64
import binascii
import io
import requests
from celery import Task
import fitz  # PyMuPDF for PDF processing
from openai import OpenAI
from app.core.celery_app import celery
from app.core.config import get_config
from app.core.supabase import supabase

config = get_config()

# Initialize OpenAI client
openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

def image_to_text(image_bytes: bytes) -> str:
    """
    Convert image to text using OpenAI's Vision API.
    Args:
        image_bytes: PNG image as bytes
    Returns:
        Extracted text from the image
    """
    try:
        # Convert bytes to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
        # Call OpenAI API
        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": config.OPENAI_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Please extract and format all the text from this image:"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=config.OPENAI_MAX_TOKENS
        )
        
        # Get the extracted text
        extracted_text = response.choices[0].message.content
        return extracted_text
        
    except Exception as e:
        print(f"Error extracting text from image: {str(e)}")
        return f"Error extracting text: {str(e)}"


def save_pdf_pages_as_images(pdf_path: str, output_dir: str) -> None:
    """
    Save each page of a PDF as a PNG image.
    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save the images in
    """
    try:
        # Verify the PDF file exists
        if not os.path.exists(pdf_path):
            raise ValueError(f"PDF file not found: {pdf_path}")
            
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Try to open the PDF
        print(f"Opening PDF file: {pdf_path}")
        doc = fitz.open(pdf_path)
        
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
            
        print(f"Processing PDF with {doc.page_count} pages")
        
        # Convert each page
        for page_num in range(doc.page_count):
            try:
                page = doc[page_num]
                
                # Get the page's pixmap (rendered image)
                matrix = fitz.Matrix(2, 2)  # 2x zoom for better quality
                pix = page.get_pixmap(matrix=matrix)
                
                # Save the pixmap as PNG
                image_path = os.path.join(output_dir, f"page-{page_num + 1}.png")
                pix.save(image_path)
                print(f"Saved page {page_num + 1} as {image_path}")
                
            except Exception as page_error:
                print(f"Error processing page {page_num + 1}: {str(page_error)}")
                continue
        
        doc.close()
        print("Successfully processed all pages")
        
    except Exception as e:
        if 'doc' in locals():
            doc.close()
        raise ValueError(f"Failed to process PDF: {str(e)}")


def get_pdf_content(url: str) -> bytes:
    """
    Download PDF from URL and return its content as bytes.
    Handles both regular PDFs and Base64 encoded PDFs.
    Returns the PDF content as bytes.
    """
    try:
        print(f"Downloading PDF from URL: {url}")
        response = requests.get(url)
        response.raise_for_status()
        content = response.content
        
        # Check if it's already a PDF
        if content.startswith(b'%PDF'):
            print("Downloaded valid PDF content")
            return content
            
        # Try to decode as Base64
        try:
            print("Attempting to decode Base64 content...")
            decoded_content = base64.b64decode(content)
            
            # Check if decoded content is a PDF
            if decoded_content.startswith(b'%PDF'):
                print("Successfully decoded Base64 PDF content")
                return decoded_content
            else:
                raise ValueError("Decoded content is not a PDF")
                
        except binascii.Error:
            raise ValueError("Content is not valid Base64")
        except Exception as e:
            raise ValueError(f"Failed to decode content: {str(e)}")
        
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to download file: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error processing PDF: {str(e)}")


def extract_pdf_images(pdf_content: bytes) -> List[bytes]:
    """
    Extract images from PDF content without saving to disk.
    Returns a list of PNG image bytes for each page.
    """
    images = []
    
    # Create a memory buffer for the PDF
    pdf_buffer = io.BytesIO(pdf_content)
    
    # Open PDF from memory
    doc = fitz.open(stream=pdf_buffer, filetype="pdf")
    
    try:
        print(f"Processing PDF with {doc.page_count} pages")
        
        # Convert each page
        for page_num in range(doc.page_count):
            try:
                page = doc[page_num]
                
                # Get the page's pixmap (rendered image)
                matrix = fitz.Matrix(2, 2)  # 2x zoom for better quality
                pix = page.get_pixmap(matrix=matrix)
                
                # Get image bytes
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)
                print(f"Processed page {page_num + 1}, image size: {len(img_bytes)} bytes")
                
            except Exception as page_error:
                print(f"Error processing page {page_num + 1}: {str(page_error)}")
                continue
        
        return images
        
    finally:
        doc.close()
        pdf_buffer.close()


class BaseTask(Task):
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        if args and isinstance(args[0], (str, UUID)):
            book_id = args[0]
            supabase.table('books').update({
                'processing_status': 'failed'
            }).eq('id', str(book_id)).execute()
        print(f"Task {task_id} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery.task(base=BaseTask, name='process_book')
def process_book(book_id: str) -> Dict[str, Any]:
    """
    Process book file in the background.
    Steps:
    1. Update book status to processing
    2. Extract text content from PDF
    3. Create chapters/contents
    4. Update book metadata (page count)
    5. Update processing status to completed
    """
    try:
        # Get book data
        book_response = supabase.table('books').select('*').eq('id', book_id).execute()
        if not book_response.data:
            raise Exception(f"Book {book_id} not found")
        book = book_response.data[0]

        # Get the download URL
        storage_path = book['storage_path']
        download_url = f"{config.SUPABASE_URL}/storage/v1/object/public/book_files/{storage_path}"
        
        # Download and process PDF in memory
        pdf_content = get_pdf_content(download_url)
        
        # Extract images from PDF
        page_images = extract_pdf_images(pdf_content)
        print(f"Successfully extracted {len(page_images)} page images")
        
        # Now you have the images in memory as bytes
        # Each image in page_images is ready to be sent to AI
        # Example: page_images[0] contains the bytes for the first page image
        
        # For demonstration, let's print the size of each image
        for i, img_bytes in enumerate(page_images):
            print(f"Page {i+1} image size: {len(img_bytes)} bytes")
            
        # Create BytesIO object for text extraction
        pdf_buffer = io.BytesIO(pdf_content)
        doc = fitz.open(stream=pdf_buffer, filetype="pdf")
        
        # Update book metadata with actual page count
        page_count = len(page_images)
        supabase.table('books').update({
            'page_count': page_count
        }).eq('id', book_id).execute()

        # Process each page with OpenAI Vision
        for page_num in range(len(page_images)):
            print(f"Processing page {page_num + 1} with OpenAI Vision...")
            # Convert image to text using OpenAI
            extracted_text = image_to_text(page_images[page_num])
            
            # Store the extracted text
            supabase.table('book_contents').insert({
                'book_id': book_id,
                'content_type': 'markdown',
                'content': extracted_text,
                'chapter_index': page_num,
                'chapter_title': f"Page {page_num + 1}"
            }).execute()
            
            print(f"Completed page {page_num + 1}")

        # Close the PDF buffer
        doc.close()
        pdf_buffer.close()

        # Update book status to completed
        supabase.table('books').update({
            'processing_status': 'completed'
        }).eq('id', book_id).execute()

        return {
            'book_id': book_id,
            'status': 'completed',
            'message': 'Book processing completed successfully',
            'page_count': page_count
        }

    except Exception as e:
        error_msg = str(e)
        # Update book status to failed
        supabase.table('books').update({
            'processing_status': 'failed',
            'error_message': error_msg
        }).eq('id', book_id).execute()
        
        
        return {
            'book_id': book_id,
            'status': 'failed',
            'message': f"Failed to process book: {error_msg}"
        }


@celery.task(name='get_book_status')
def get_book_status(book_id: str) -> Dict[str, Any]:
    """
    Get book processing status and metadata
    """
    try:
        response = supabase.table('books').select(
            'id',
            'processing_status',
            'page_count',
        ).eq('id', book_id).execute()
        
        if not response.data:
            return {
                'book_id': book_id,
                'status': 'not_found',
                'message': f"Book {book_id} not found"
            }
        
        book = response.data[0]
        return {
            'book_id': book_id,
            'status': book['processing_status'],
            'message': book.get('error_message') or f"Book processing status: {book['processing_status']}",
            'page_count': book.get('page_count')
        }
    except Exception as e:
        return {
            'book_id': book_id,
            'status': 'error',
            'message': f"Failed to get book status: {str(e)}"
        }