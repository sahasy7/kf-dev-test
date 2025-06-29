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
async def upload_single_file(file: UploadFile = File(...), company_name: str = Form(...)):
    """
    File(...) tells FastAPI:
    - This endpoint expects a file upload
    - The file parameter is required (... = required)
    - Parse multipart/form-data automatically
    """
    print(f"📁 Received file: {file.filename}")
    print(f"📋 Content type: {file.content_type}")
    print(f"📏 File size: {file.size} bytes")
    
    # Read file content
    content = await file.read()
    file_extension = file.filename.split('.')[-1].lower()
    
    # Save file to disk
    """file_path = os.path.join(UPLOAD_DIR, f"single_{company_name}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content) **/"""
    No_flag  = True
    upload_doc = await file_upload(content, company_name,file_extension,No_flag)
    Doc_collect = await analyze_document_complete(upload_doc)
    kf_file,kf_name, kf_extension,kf_flg = await knowledge_ai(Doc_collect,company_name)
    upload_kf = await file_upload(kf_file,kf_name, kf_extension,kf_flg)
    
    
    
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
               "content": kf_data,
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
   print(data)
   print(result)
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
