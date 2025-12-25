from pydantic import BaseModel
from typing import List

class StatusRequest(BaseModel):
    sessionId: str
    status: str

class InputData(BaseModel):
    input_data: str

class LinksRequest(BaseModel):
    links: List[str]