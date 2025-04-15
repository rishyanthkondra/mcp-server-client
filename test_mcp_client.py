import asyncio
import json
from mcp import ClientSession, types
from mcp.client.sse import sse_client


# Define the handle_sampling_message to return the expected response format
async def handle_sampling_message(message: types.CreateMessageRequestParams):
    return types.CreateMessageResult(
        role='assistant',
        content=types.TextContent(
            type='text',
            text='Hello from SSE model',
        ),
        model='gpt-3.5-turbo',
        stopReason='endTurn',
    )


# Function to test the 'get_weather' tool
async def test_weather_tool(session: ClientSession):
    print('\n=== Testing get_weather tool ===')
    cities = ['Hyderabad', 'Chennai', 'Mumbai', 'Delhi']
    for city in cities:
        try:
            result = await session.call_tool('get_weather', arguments={'location': city})
            print(f'🌦 Weather in {city}: {result['content']['text']}')
        except Exception as e:
            print(f'[ERROR] Weather for {city}: {e}')


# Function to test the 'user_data' resource
async def test_user_data(session: ClientSession):
    print('\n=== Testing user_data resource ===')
    for user_id in ['1', '2', '3']:
        try:
            # Construct valid user data URL (replace with your actual server URL)
            user_data_url = f'http://0.0.0.0:8000/sse/user_data/{user_id}'
            result, mime = await session.read_resource(user_data_url)
            print(f'👤 User {user_id} (MIME: {mime})')
            if mime == 'application/json':
                data = json.loads(result)
                print(f'  Name: {data.get('fullname')}')
                print(f'  Location: {data.get('location')}')
                print(f'  Group: {data.get('group_id')}')
            else:
                print(f'  Raw: {result}')
        except Exception as e:
            print(f'[ERROR] User {user_id}: {e}')


# Main function to run the tests
async def run():
    base_url = 'http://0.0.0.0:8000/sse'  # Make sure the URL is correct for the SSE connection
    print(f'🔗 Connecting to SSE MCP server at {base_url}...')

    try:
        async with sse_client(base_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()  # Initialize the session
                print('✅ Connection established!')

                print('\n📜 Listing available prompts:')
                try:
                    prompts = await session.list_prompts()
                    if prompts:
                        for name, desc in prompts.items():
                            print(f'  📄 {name}: {desc}')
                    else:
                        print("No prompts available.")
                except Exception as e:
                    print(f'[ERROR] Failed to list prompts: {e}')
                
                print('\n🧰 Listing available tools:')
                try:
                    tools = await session.list_tools()
                    if tools:
                        for name, desc in tools.items():
                            print(f'  🔧 {name}: {desc}')
                    else:
                        print("No tools available.")
                except Exception as e:
                    print(f'[ERROR] Failed to list tools: {e}')

                # Test the weather tool and user data
                await test_weather_tool(session)
                await test_user_data(session)

    except Exception as e:
        print(f'[ERROR] Connection to SSE server failed: {e}')


# Run the test
if __name__ == '__main__':
    print('🚀 Running MCP SSE client tests...\n')
    asyncio.run(run())
