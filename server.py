from fastapi import FastAPI
from models import User
from mcp.server.fastmcp import FastMCP
from fastapi.responses import StreamingResponse
import asyncio
import json

# Create a FastAPI app
app = FastAPI()

# Create an MCP server and link it to the FastAPI app
server = FastMCP('get_user_data')

# Event generator to send SSE events periodically
async def event_generator():
    # You can add any logic to send events based on different conditions
    while True:
        await asyncio.sleep(5)  # Emit event every 5 seconds for demonstration
        yield f"event: message\ndata: {{'status': 'Event sent from server!'}}\n\n"

# # Create a route to stream events via SSE
# @app.get("/mcp/sse")
# async def sse_stream():
#     return StreamingResponse(event_generator(), media_type="text/event-stream")

@server.tool()
def get_weather(location: str) -> str:
    '''Get weather summary given a location'''
    return {
        'Hyderabad': 'Sunny, 39C, feels like 43C, Visibility 15km, UV index 10, Humidity 10%',
        'Chennai': 'Stormy, 26C, feels like 36C, Visibility 8km, UV index 7, Humidity 20%',
        'Mumbai': 'Heavy rain, 24C, feels like 18C, Visibility 1km, UV index 4, Humidity 90%',
    }.get(location, f'Unable to get weather summary at the moment for {location}')
    

@server.prompt()
def weather_data() -> str:
    return '''
    - Use this prompt only in cases where general comparisons are being drawn
    - All cities for which weather information is available: Hyderabad, Chennai, Mumbai
    Examples:
        - What is most humid city right now?
        - Where is the weather coldest?
    '''


@server.resource('user_data://{user_id}')
def get_user(user_id: str) -> str:
    '''Get user information, given a user_id'''
    user_id = int(user_id)
    return User(
        user_id=user_id,
        fullname='Ramesh' if user_id < 2 else 'Suresh',
        group_id='google.com',
        location='Hyderabad' if user_id < 2 else 'Chennai'
    ).model_dump_json()

# @app.post("/messages/")
# async def handle_message(session_id: str):
#     print(f"Received message for session_id: {session_id}")
#     # Optionally you can return relevant information about the message here
#     return {"status": "Message received for session", "session_id": session_id}

# Mount the server's SSE API on /mcp
app.mount('/', server.sse_app())

# Start the server when this file is run directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
