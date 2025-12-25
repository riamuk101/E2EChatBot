from typing import Optional, Callable, Awaitable, Set
from pydantic import BaseModel, Field
import asyncio
import json
import aiohttp  # Add this import
import time
import websockets

N8N_HOST = "localhost"
BACKEND_HOST = "localhost"


class Pipe:
    class Valves(BaseModel):
        n8n_url: str = Field(
            default=f"http://{N8N_HOST}:5678/webhook/invoke_n8n_agent_simple"
        )
        websocket_url: str = Field(default=f"ws://{BACKEND_HOST}:8001/ws/")
        n8n_bearer_token: str = Field(default="...")
        input_field: str = Field(default="chatInput")
        response_field: str = Field(default="output")
        emit_interval: float = Field(
            default=0.5, description="Interval in seconds between status emissions"
        )
        enable_status_indicator: bool = Field(
            default=True, description="Enable or disable status indicator emissions"
        )

    def __init__(self):
        self.type = "pipe"
        self.id = "n8n_pipe"
        self.name = "N8N Pipe"
        self.valves = self.Valves()
        self.last_emit_time = 0
        self.chat_id = None

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        print(f"inlet:{__name__}")
        print(f"user: {user}")
        print(f"body: {body}")
        # Store the chat_id from body
        self.chat_id = body.get("chat_id")
        print(f"Stored chat_id: {self.chat_id}")
        return body

    async def emit_status(
        self,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        level: str,
        message: str,
        done: bool,
        type: str = "status",
    ):
        current_time = time.time()

        if __event_emitter__ and self.valves.enable_status_indicator:
            if type == "status":
                await __event_emitter__(
                    {
                        "type": type,
                        "data": {
                            "status": "complete" if done else "in_progress",
                            "level": level,
                            "description": message,
                            "done": done,
                        },
                    }
                )
            elif type == "message":
                await __event_emitter__(
                    {
                        "type": type,
                        "data": {"content": message},
                    }
                )

            self.last_emit_time = current_time
        await asyncio.sleep(0)  # Changed from 1 to 0 for minimal delay

    async def start_websocket_listener(
        self, session_id: str, __event_emitter__: Callable[[dict], Awaitable[None]]
    ):
        ws_url = f"{self.valves.websocket_url}{session_id}"
        async with websockets.connect(ws_url) as websocket:
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                if data["status"] == "done":
                    await self.emit_status(__event_emitter__, "info", "Completed", True)
                    # Close the websocket connection
                    await websocket.close()
                    break
                else:
                    await self.emit_status(
                        __event_emitter__, "info", f"{data['status']}", False
                    )

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __event_call__: Callable[[dict], Awaitable[dict]] = None,
    ) -> Optional[dict]:
        session_id = __user__["id"]

        if __event_emitter__:
            asyncio.create_task(
                self.start_websocket_listener(session_id, __event_emitter__)
            )

        messages = body.get("messages", [])
        question = messages[-1]["content"]
        if "Prompt: " in question:
            question = question.split("Prompt: ")[-1]

        try:
            headers = {
                "Authorization": f"Bearer {self.valves.n8n_bearer_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "sessionId": session_id,
                "chatInput": question,
                "history": messages[:-1],
            }

            # Emit status before making the request
            await self.emit_status(
                __event_emitter__,
                "info",
                "Sending request to n8n",
                False,
            )

            # Use aiohttp for async HTTP request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.valves.n8n_url, json=payload, headers=headers
                ) as response:
                    if response.status == 200:
                        n8n_response = (await response.json())[
                            self.valves.response_field
                        ]
                    else:
                        error_text = await response.text()
                        raise Exception(f"Error: {response.status} - {error_text}")

            # Emit status after receiving response
            await self.emit_status(
                __event_emitter__,
                "info",
                "Response received from n8n",
                False,
            )

            await asyncio.sleep(0)  # Allow event loop to process other tasks
            body["messages"].append({"role": "assistant", "content": n8n_response})

            await self.emit_status(
                __event_emitter__,
                "status",
                "Processing complete",
                True,
            )

        except Exception as e:
            await self.emit_status(
                __event_emitter__,
                "error",
                f"Error during sequence execution: {str(e)}",
                True,
            )
            return {"error": str(e)}

        return n8n_response


# Example usage for testing
async def main():
    pipe = Pipe()

    async def mock_emitter(event):
        print(f"Emitting: {event}")

    body = {"messages": [{"role": "user", "content": "test"}]}
    result = await pipe.pipe(
        body, __user__={"id": "123"}, __event_emitter__=mock_emitter
    )
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
