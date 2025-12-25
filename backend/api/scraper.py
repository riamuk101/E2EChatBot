from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import requests
from bs4 import BeautifulSoup
import json

router = APIRouter()

class InputData(BaseModel):
    input_data: str

def parse_input(input_str: str) -> List[str]:
    try:
        cleaned = input_str.replace("```json", "").replace("```", "").strip()
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = json.loads(cleaned)
        data = json.loads(cleaned)
        return data.get("links", [])
    except json.JSONDecodeError:
        return []

def get_body_content(url: str) -> str:
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        body = soup.find("body")
        return body.get_text(strip=True) if body else "No body content found"
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Error fetching URL {url}: {e}")

@router.post("/scrape/")
async def fetch_bodies(input_data: InputData):
    try:
        links = parse_input(input_data.input_data)
        result = ""
        for link in links:
            try:
                content = get_body_content(link)
                result += f"URL: {link}\nContent: {content}\n\n"
            except HTTPException:
                continue
        return {"data": result}
    except Exception as e:
        return {"data": "", "error": str(e)}
