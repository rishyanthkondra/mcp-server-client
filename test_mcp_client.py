import asyncio
import json
from mcp import ClientSession
from mcp.client.sse import sse_client

# Function to test the 'get_weather' tool
async def test_weather_tool(session: ClientSession):
    print('\n=== Testing get_weather tool ===')
    cities = ['Hyderabad', 'Chennai', 'Mumbai', 'Delhi']
    for city in cities:
        try:
            result = await session.call_tool('get_weather', arguments={'location': city})
            print(f'🌦 Weather in {city}: {result}')
        except Exception as e:
            print(f'[ERROR] Weather for {city}: {e}')

async def test_get_prompt(session: ClientSession):
    print('\n=== Testing weather_data prompt ===')
    try:
        result = await session.get_prompt('weather_data')
        print(f'🌦 weather_data prompt: {result}')
    except Exception as e:
        print(f'[ERROR] Weather prompt: {e}')


# Function to test the 'user_data' resource
async def test_user_data(session: ClientSession):
    print('\n=== Testing user_data resource ===')
    for user_id in ['1', '2']:
        try:
            # Construct valid user data URL (replace with your actual server URL)
            user_data_url = f'resource://user_data/{user_id}'
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
                    response = await session.list_prompts()
                    available_prompts = [json.dumps(prompt.__dict__, indent=2) for prompt in response.prompts]
                    print(*available_prompts, sep='\n')
                except Exception as e:
                    print(f'[ERROR] Failed to list prompts: {e}')
                
                print('\n🧰 Listing available tools:')
                try:
                    response = await session.list_tools()
                    available_tools = [json.dumps(tool.__dict__, indent=2) for tool in response.tools]
                    print(*available_tools, sep='\n')
                except Exception as e:
                    print(f'[ERROR] Failed to list tools: {e}')
                    
                print('\n🍔 Listing available resources:')
                try:
                    response = await session.list_resources()
                    available_resources = [json.dumps(resource.__dict__, indent=2) for resource in response.resources]
                    print(*available_resources, sep='\n')
                except Exception as e:
                    print(f'[ERROR] Failed to list tools: {e}')
                
                print('\n🎶 Listing available resources templates:')
                try:
                    response = await session.list_resource_templates()
                    available_template = [json.dumps(template.__dict__, indent=2) for template in response.resourceTemplates]
                    print(*available_template, sep='\n')
                except Exception as e:
                    print(f'[ERROR] Failed to list tools: {e}')

                # Test the weather tool and user data
                await test_weather_tool(session)
                await test_get_prompt(session)
                await test_user_data(session)

    except Exception as e:
        print(f'[ERROR] Connection to SSE server failed: {e}')


# Run the test
if __name__ == '__main__':
    print('🚀 Running MCP SSE client tests...\n')
    asyncio.run(run())
