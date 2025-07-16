from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from typing import List, Optional
import os
from dotenv import load_dotenv
from datetime import datetime
from azure.storage.blob import  BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from openai import AzureOpenAI
from fpdf import FPDF
import textwrap
import requests
from bs4 import BeautifulSoup
import re
import extruct
from w3lib.html import get_base_url
import json


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
           blob_service_client = BlobServiceClient(account_url=s_url, credential=s_token )
           container_client = blob_service_client.get_container_client(container=container_name)
           container_client.upload_blob(name=blob_name, data=file_data, overwrite=True)
           return blob_name
       except Exception as e:
           return f"Upload failed: {str(e)}"
   else:
       try:
           blob_service_client = BlobServiceClient(account_url=s_url, credential=s_token)
           container_client = blob_service_client.get_container_client(container=container_name)
           f_file_data = file_data.encode('latin-1')
           container_client.upload_blob(name=comp_name, data=f_file_data, overwrite=True)
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

    if file:
        print(f"📁 Received file: {file.filename}")
        print(f"📋 Content type: {file.content_type}")
        # FastAPI UploadFile doesn't have a .size attribute, so don't use it directly

        content = await file.read()
        file_extension = file.filename.split('.')[-1].lower()
        No_flag = True

        upload_doc = await file_upload(content, company_name, file_extension, No_flag)
        Doc_collect = await analyze_document_complete(upload_doc)
    else:
        Doc_collect = {"document_text": "No document uploaded"}

    if company_url:
        url_data = await extract_url(company_url)
    else:
        url_data = {"url_data": "No company URL provided"}

    combined_data = {
        "document_data": Doc_collect,
        "url_data": url_data
    }

    kf_file, kf_name, kf_extension, kf_flg = await knowledge_ai(combined_data, company_name)
    upload_kf = await file_upload(kf_file, kf_name, kf_extension, kf_flg)

    return Response(
        content=kf_file.encode('latin-1'),
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={kf_name}'}
    )


async def analyze_document_complete(formUrl: str) -> dict:
    
    Final_url = f"https://knowfilestorage.blob.core.windows.net/devknoweldgefile/devknoweldgefile/{formUrl}"
    
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
        return all_text.strip()
    else:
        return f"No Content found"
    


    
async def knowledge_ai(data: str, file_name:str):
   kf_data = data
   client = AzureOpenAI(
       api_version="2024-12-01-preview",
       azure_endpoint=end,
       api_key=openi_key
   )
   
   response = client.chat.completions.create(
       messages=[
           {
               "role": "system",
               "content": """You are a helpful assistant. make a knoweldge file with deailted inderstanding where input data will be given
               Generate a document or text (like a summary, report, or info sheet) using only characters that are compatible with the latin-1 (ISO-8859-1) encoding.
Avoid using:

Emojis

Smart quotes (“ ” ‘ ’)

Em dashes or en dashes (— –)

Ellipses (…)

Any characters outside basic Western European characters (e.g., no non-Latin scripts)

Use only standard ASCII or latin-1 characters like regular quotes (" and '), dashes (-), etc.
Format the content clearly with headings, bullet points, and tables if needed — but keep all characters within the latin-1 character set.""" ,
           },
           {
               "role": "user",
               "content": json.dumps(kf_data, indent=2),
            }
        ],
        max_completion_tokens= None,
        temperature=1.0,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        model="gpt-4.1-mini"
    )
   
   result = response.choices[0].message.content
   f_result = text_to_pdf(result)
   flag = False
   name = f"{file_name}_KnoweldgeFile.pdf"
   extension = None

   return f_result,name,extension,flag


def text_to_pdf(text_content):

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Courier', '', 10)  # Monospaced font preserves table layout

    if not text_content or not str(text_content).strip():
        pdf.cell(0, 10, "Error: No text content provided", 0, 1)
        return pdf.output(dest='S')

    text_content = str(text_content)

    # Split content into lines
    lines = text_content.split('\n')
    wrap_width = 100  # Characters per line, adjust as needed

    for line in lines:
        if not line.strip():
            pdf.ln(5)
            continue

        # Wrap lines longer than wrap_width
        wrapped_lines = textwrap.wrap(line, width=wrap_width)
        for wrapped_line in wrapped_lines:
            pdf.cell(0, 5, wrapped_line, ln=1)

    return pdf.output(dest='S')

async def extract_url(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    html = response.text
    soup = BeautifulSoup(html, 'lxml')  # You can also use 'html.parser'

    base_url = get_base_url(html, url)

    # Title & Meta
    title = soup.title.string if soup.title else ''
    meta_desc = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta_desc["content"] if meta_desc else ''

    # Keywords & Author
    meta_keywords = soup.find("meta", attrs={"name": "keywords"})
    meta_keywords = meta_keywords["content"] if meta_keywords else ''
    meta_author = soup.find("meta", attrs={"name": "author"})
    meta_author = meta_author["content"] if meta_author else ''

    # All Text Content
    all_text = soup.get_text(separator=' ', strip=True)

    # Links
    links = [a['href'] for a in soup.find_all('a', href=True)]

    # Images
    images = [img['src'] for img in soup.find_all('img', src=True)]

    # Emails and Phone Numbers
    emails = list(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html)))
    phones = list(set(re.findall(r'\+?\d[\d\s().-]{7,}\d', html)))

    # Structured Data (JSON-LD, Microdata, RDFa, etc.)
    structured_data = extruct.extract(html, base_url=base_url)

    # Headings
    headings = {
        "h1": [h.get_text(strip=True) for h in soup.find_all('h1')],
        "h2": [h.get_text(strip=True) for h in soup.find_all('h2')],
        "h3": [h.get_text(strip=True) for h in soup.find_all('h3')],
    }

    # Return everything
    return {
        "Title": title,
        "All Text": all_text
    }
