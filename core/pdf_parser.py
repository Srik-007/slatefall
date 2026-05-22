import os
import re
import pymupdf as fitz
from dotenv import load_dotenv
load_dotenv()

PDF_PATH=os.getenv("PDF_PATH", "SLATEFALL_DOSSIER.pdf")

SECTION_COUNT=10

def extract_all_text(pdf_path:str)->str:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF not found at '{pdf_path}'"
        )
    doc=fitz.open(pdf_path)
    pages_text=[]
    for page in doc:
        text=page.get_text("text")
        pages_text.append(text)
    doc.close()
    full_text="\n".join(pages_text)
    return full_text

def split_into_sections(full_text:str)->dict[int,str]:
    pattern=re.compile(r"Section\s+(\d+)\.",re.IGNORECASE)
    matches=list(pattern.finditer(full_text))
    if not matches:
        raise ValueError(
            "No section headers found in PDF."
            "Check that the PDF is machine readable and not scanned."
        )
    sections={}
    for i, match in enumerate(matches):
        section_num=int(match.group(1))
        start=match.start()
        if i+1<len(matches):
            end=matches[i+1].start()
        else:
            end=len(full_text)
        section_text=full_text[start:end].strip()
        if 1<=section_num<=SECTION_COUNT:
            sections[section_num]=section_text
    return sections
def get_sections(section_ids:list[int])->dict[int,str]:
    full_text=extract_all_text(PDF_PATH)
    all_sections=split_into_sections(full_text)
    result={}
    for sid in section_ids:
        if sid<1 or sid>SECTION_COUNT:
            raise ValueError(
                f"Section {sid} is out of range."
                f"Valid sections are 1 through {SECTION_COUNT}"
            )
        if sid not in all_sections:
            raise ValueError(
                f"Section {sid} was not found in the PDF."
                f"This may indicate a parsing issue"
            )
        result[sid]=all_sections[sid]
    return result
def list_all_sections()->dict[int,str]:
    full_text=extract_all_text(PDF_PATH)
    all_sections=split_into_sections(full_text)
    preview={}
    for num,text in sorted(all_sections.items()):
        preview[num]= text[:200].replace("\n"," ")
    return preview