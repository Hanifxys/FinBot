import io
import json
import logging
import asyncio
from typing import Optional, List, Any
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

    async def parse_financial_document(self, text: str, model_client: Any) -> dict:
        """
        Deep parsing of financial text (Balance Sheets, Income Statements).
        Returns structured JSON of financial metrics.
        """
        try:
            prompt = f"""
            Analyze the following financial text and extract key performance indicators (KPIs).
            The document could be in Indonesian or English.
            
            Extract:
            - Revenue / Total Pemasukan
            - Net Income / Laba Bersih
            - Total Assets / Total Aset
            - Total Liabilities / Total Liabilitas
            - Cash on Hand
            - Operating Margin
            - Ticker (if any)
            - Period (Year/Quarter)
            
            Text Content:
            {text[:5000]}
            
            Return JSON format:
            {{
                "metadata": {{"ticker": "str", "period": "str", "currency": "str"}},
                "metrics": {{
                    "revenue": float,
                    "net_income": float,
                    "total_assets": float,
                    "total_liabilities": float,
                    "cash": float
                }},
                "ratios": {{"operating_margin": float, "debt_to_equity": float}},
                "summary": "brief executive summary"
            }}
            """
            chat_completion = model_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            import json
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"Financial document parsing failed: {e}")
            return {"error": str(e)}
