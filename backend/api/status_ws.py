from fastapi import APIRouter, WebSocket
from pydantic import BaseModel
import asyncio

router = APIRouter()
status_store = {}

class StatusRequest(BaseModel):
    sessionId: str
    status: str

@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        if session_id in status_store:
            await websocket.send_json({"status": status_store[session_id]})

        while True:
            await asyncio.sleep(0.5)
            if session_id in status_store:
                await websocket.send_json({"status": status_store[session_id]})
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

@router.post("/n8n-webhook/")
async def handle_n8n_webhook(request: StatusRequest):
    if request.status == "clear":
        status_store.pop(request.sessionId, None)
        return {"message": f"Status cleared for {request.sessionId}"}
    status_store[request.sessionId] = request.status
    return {"message": f"Status {request.status} for {request.sessionId} stored"}
