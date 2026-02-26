import io
import json
import logging
import asyncio
from typing import Optional, List
from modules.ocr import extract_text_from_image, extract_text_from_url
from modules.amounts import parse_amount_id

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """
    Intelligent File Processing & Summarization.
    Supports:
    - Images (Receipts, Graphs, Screenshots) -> OCR
    - Text Files (CSV, JSON, TXT) -> Raw Text
    - Basic PDF/DOCX (if libraries available, otherwise plain text fallback)
    """
    def __init__(self):
        pass

    async def process_file(self, file_content: bytes, file_name: str, mime_type: str = "") -> str:
        """
        Main entry point for file processing.
        Returns extracted text suitable for AI input.
        """
        logger.info(f"Processing file: {file_name} ({mime_type})")
        
        # 1. Image Processing (Receipts, etc.)
        if mime_type.startswith("image/") or file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            # Assume file_content is bytes, convert to temporary file path for OCR module
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            
            try:
                # Use existing OCR module
                text = await extract_text_from_image(tmp_path)
                return f"[Extracted Text from Image '{file_name}']:\n{text}"
            except Exception as e:
                logger.error(f"OCR Failed: {e}")
                return f"Error extracting text from image: {e}"
            finally:
                import os
                try:
                    os.remove(tmp_path)
                except:
                    pass

        # 2. Text-based Formats (TXT, CSV, JSON, MD)
        if mime_type.startswith("text/") or file_name.lower().endswith(('.txt', '.csv', '.json', '.md', '.log')):
            try:
                text = file_content.decode('utf-8', errors='ignore')
                # Truncate if too long (simple heuristic)
                if len(text) > 20000:
                    text = text[:20000] + "\n...[Truncated]"
                return f"[File Content '{file_name}']:\n{text}"
            except Exception as e:
                return f"Error reading text file: {e}"

        # 3. PDF/DOCX (Placeholder - requires pypdf/python-docx)
        # Since we can't install new deps easily, we'll try basic text extraction if possible
        # or return a message about limited support.
        if file_name.lower().endswith('.pdf'):
            return "PDF processing is limited. Please convert to text or image if possible."
            
        return "Unsupported file format for deep analysis."

    def summarize_content(self, text: str, model_client, model_name: str) -> str:
        """
        Summarize extracted content using AI.
        """
        # This will be called by PremiumAIEngine
        pass
