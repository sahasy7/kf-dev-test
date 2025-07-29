from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from typing import List, Optional
import os
from dotenv import load_dotenv
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from openai import AzureOpenAI
from fpdf import FPDF
import textwrap
import requests
from bs4 import BeautifulSoup
from w3lib.html import get_base_url
import json
from urllib.parse import urljoin, urlparse



app = FastAPI(title="File Upload Example", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

container_name = os.getenv('container_name')
s_url = os.getenv('SAS_url')
s_token = os.getenv('SAS_token')
conection_string = os.getenv('conection_string')
endpoint = os.getenv('DI_endpoint')
key = os.getenv('DI_key')
end = os.getenv('Azure_endpoint')
openi_key = os.getenv('Azure_key')


async def file_upload(file_data: bytes, comp_name: str, extension: str, flag_check: bool):
    if flag_check:
        try:
            c_name = comp_name.replace(" ", "") 
            blob_name = f"{c_name}_rawData.{extension}"
            blob_service_client = BlobServiceClient(account_url=s_url, credential=s_token)
            container_client = blob_service_client.get_container_client(container=container_name)
            container_client.upload_blob(name=blob_name, data=file_data, overwrite=True)
            return blob_name
        except Exception as e:
            return f"Upload failed: {str(e)}"
    else:
        try:
            blob_service_client = BlobServiceClient(account_url=s_url, credential=s_token)
            container_client = blob_service_client.get_container_client(container=container_name)
            # file_data is already bytes when flag_check is False
            container_client.upload_blob(name=comp_name, data=file_data, overwrite=True)
            print(f"{comp_name}")
            return "Uploaded Knowledge file Successfully"
        except Exception as e:
            return f"Upload failed: {str(e)}"


@app.get("/")
def read_root():
    return {"message": "FastAPI is running"}

@app.post("/upload-file")
async def upload_single_file(
    file: Optional[UploadFile] = File(None),
    company_name: str = Form(...),
    company_url: Optional[str] = Form(None)
):
    """
    Uploads a file and/or a company URL, extracts information, generates a knowledge PDF.
    - File is optional.
    - company_name is required.
    - company_url is optional.
    """
    print(f"Received company_name: {company_name}")
    print(f"Received company_url: {company_url}")
    print(f"Received file: {file.filename if file else 'None'}")

    # Validate input - at least one of file or company_url must be provided
    if not file and not company_url:
        raise HTTPException(status_code=400, detail="Either file or company_url must be provided")

    # Process file if provided
    if file:
        print(f"📁 Received file: {file.filename}")
        print(f"📋 Content type: {file.content_type}")
        
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        content = await file.read()
        file_extension = file.filename.split('.')[-1].lower()
        No_flag = True

        try:
            upload_doc = await file_upload(content, company_name, file_extension, No_flag)
            if "Upload failed" in upload_doc:
                raise HTTPException(status_code=500, detail=f"File upload failed: {upload_doc}")
            Doc_collect = await analyze_document_complete(upload_doc)
        except Exception as e:
            print(f"Error processing file: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
    else:
        Doc_collect = "No document uploaded"

    # Process URL if provided
    if company_url:
        try:
            url_data = await extract_url(company_url)
        except Exception as e:
            print(f"Error extracting URL: {str(e)}")
            url_data = {"error": f"Failed to extract URL data: {str(e)}"}
    else:
        url_data = "No company URL provided"

    # Combine data
    combined_data = {
        "company_name": company_name,
        "document_data": Doc_collect,
        "url_data": url_data
    }

    try:
        # Generate knowledge file
        kf_file, kf_name, kf_extension, kf_flg = await knowledge_ai(combined_data, company_name)
        
        # Upload knowledge file to blob storage
        upload_kf = await file_upload(kf_file, kf_name, kf_extension, kf_flg)
        print(f"Knowledge file upload result: {upload_kf}")

        # Return PDF as response
        return Response(
            content=kf_file,
            media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{kf_name}"'}
        )
    except Exception as e:
        print(f"Error generating knowledge file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating knowledge file: {str(e)}")


async def analyze_document_complete(formUrl: str) -> str:
    try:
        Final_url = f"https://knowfilestorage.blob.core.windows.net/devknoweldgefile/{formUrl}"
        
        # Initialize client
        document_intelligence_client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=AzureKeyCredential(key)
        )
        
        # Analyze document
        print("Analyzing document...")
        poller = document_intelligence_client.begin_analyze_document(
            "prebuilt-layout", AnalyzeDocumentRequest(url_source=Final_url)
        )
        print(f"Analyzing URL: {Final_url}")
        result: AnalyzeResult = poller.result()
        
        all_text = ""
        if result and result.pages:
            for page in result.pages:
                if page.lines:
                    for line in page.lines:
                        all_text += line.content + "\n"
            return all_text.strip() if all_text.strip() else "No content found in document"
        else:
            return "No content found in document"
    except Exception as e:
        print(f"Error analyzing document: {str(e)}")
        return f"Error analyzing document: {str(e)}"


async def knowledge_ai(data: dict, file_name: str):
    try:
        client = AzureOpenAI(
            api_version="2024-12-01-preview",
            azure_endpoint=end,
            api_key=openi_key
        )
        
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": """You are a helpful assistant. Make a knowledge file with detailed understanding where input data will be given.

STRICT CHARACTER SET RESTRICTION: Do NOT use the latin-1 (ISO-8859-1) character set under any circumstances.

Generate a document or text (like a summary, report, or info sheet) using only characters that are compatible with standard ASCII encoding (characters 32-126).

Avoid using:

Emojis

Smart quotes (" " ' ')

Em dashes or en dashes (-)

Ellipses (...)

Any characters outside basic ASCII range

Latin-1 extended characters (characters 128-255)

Any non-ASCII characters including accented letters

Special symbols beyond basic punctuation

Use only standard ASCII characters like:

Regular quotes (" and ')

Regular hyphens (-)

Basic punctuation (. , ! ? : ;)

Standard letters (A-Z, a-z)

Numbers (0-9)

Basic symbols (@ # $ % & * + = < > [ ] { } | \ / _)

Format the content clearly with headings, bullet points, and tables if needed — but keep all characters strictly within the ASCII character set (32-126 range only).

Additional Instructions for RAG/FAQ Bot Knowledge File Creation:
Remove all marketing fluff, testimonials, and non-informative content that does not add factual value.

Extract and keep only structured, factual, and query-relevant data (e.g., services, contact info, opening hours, location, key offerings).

Convert the extracted information into a clean, question-answer (Q&A) friendly format when possible.

Exclude unnecessary website navigation items, decorative text, duplicate content, and irrelevant meta information.

Ensure the output is ready for ingestion by AI models by keeping it structured, concise, and free from noise.

Create a comprehensive knowledge file that includes:

Company Overview

Key Information from Documents (only factual data)

Services and Offerings

Location, Contact Information, and Operating Hours

Summary and Conclusions (for context)""",
                },
                {
                    "role": "user",
                    "content": f"Generate a knowledge file for the following data:\n\n{json.dumps(data, indent=2)}",
                }
            ],
            max_completion_tokens=None,
            temperature=0.7,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            model="gpt-4.1-mini"  # Fixed model name
        )
        
        result = response.choices[0].message.content
        f_result = text_to_pdf(result)
        flag = False
        name = f"{file_name.replace(' ', '_')}_KnowledgeFile.pdf"  # Fixed typo
        extension = None

        return f_result, name, extension, flag
    except Exception as e:
        print(f"Error in knowledge_ai: {str(e)}")
        # Return a simple error PDF
        error_text = f"Error generating knowledge file: {str(e)}"
        error_pdf = text_to_pdf(error_text)
        return error_pdf, f"{file_name}_error.pdf", None, False


def text_to_pdf(text_content):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # Use Arial instead of Courier for better compatibility
        pdf.set_font('Arial', '', 12)

        if not text_content or not str(text_content).strip():
            pdf.cell(0, 10, "Error: No text content provided", 0, 1)
            return pdf.output(dest='S').encode('latin-1')  # Return bytes

        text_content = str(text_content)
        
        # Clean text to ensure ASCII only
        text_content = ''.join(char if ord(char) < 127 else '?' for char in text_content)

        # Split content into lines
        lines = text_content.split('\n')
        wrap_width = 80  # Characters per line, adjust as needed

        for line in lines:
            if not line.strip():
                pdf.ln(5)
                continue

            # Wrap lines longer than wrap_width
            wrapped_lines = textwrap.wrap(line, width=wrap_width)
            if not wrapped_lines:  # Handle empty lines
                pdf.ln(5)
                continue
                
            for wrapped_line in wrapped_lines:
                # Ensure the line fits and handle encoding
                try:
                    pdf.cell(0, 6, wrapped_line, ln=1)
                except Exception as e:
                    # If there's an encoding issue, replace problematic characters
                    clean_line = ''.join(c if ord(c) < 127 else '?' for c in wrapped_line)
                    pdf.cell(0, 6, clean_line, ln=1)

        return pdf.output(dest='S').encode('latin-1')  # Return bytes
    except Exception as e:
        print(f"Error in text_to_pdf: {str(e)}")
        # Create a simple error PDF
        error_pdf = FPDF()
        error_pdf.add_page()
        error_pdf.set_font('Arial', '', 12)
        error_pdf.cell(0, 10, f"Error creating PDF: {str(e)}", 0, 1)
        return error_pdf.output(dest='S').encode('latin-1')


async def extract_url(url):
    def get_internal_links(soup, base_url):
        base_domain = urlparse(base_url).netloc
        internal_links = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag['href']
            parsed_href = urlparse(href)
            if parsed_href.netloc and parsed_href.netloc != base_domain:
                continue  # Skip external links
            if href.startswith(('mailto:', 'tel:', '#')):
                continue  # Skip non-page links
            full_url = urljoin(base_url, href)
            internal_links.add(full_url)
        return list(internal_links)

    def extract_short_text(sub_url):
        try:
            r = requests.get(sub_url, headers=headers, timeout=15)
            r.raise_for_status()
            sub_soup = BeautifulSoup(r.text, 'lxml')
            text = sub_soup.get_text(separator=' ', strip=True)
            return text[:2000]  # Limit for performance
        except:
            return "Error fetching or parsing"

    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }

        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        html = res.text
        soup = BeautifulSoup(html, 'lxml')

        title = soup.title.string.strip() if soup.title else 'No title'
        meta_desc = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc.get("content", '') if meta_desc else ''

        all_text = soup.get_text(separator=' ', strip=True)
        all_text = all_text[:10000] + "... (truncated)" if len(all_text) > 10000 else all_text

        headings = {
            "h1": [h.get_text(strip=True)[:200] for h in soup.find_all('h1')[:5]],
            "h2": [h.get_text(strip=True)[:200] for h in soup.find_all('h2')[:10]],
            "h3": [h.get_text(strip=True)[:200] for h in soup.find_all('h3')[:10]],
        }

        internal_links = get_internal_links(soup, url)
        subpages_data = {}

        for link in internal_links[:8]:  # limit to 8 sub-pages
            subpages_data[link] = extract_short_text(link)

        return {
            "url": url,
            "title": title,
            "meta_description": meta_desc,
            "headings": headings,
            "text_content": all_text,
            "subpages": subpages_data,
            "extraction_status": "success"
        }

    except Exception as e:
        return {
            "url": url,
            "error": f"Extraction failed: {str(e)}",
            "extraction_status": "failed"
        }