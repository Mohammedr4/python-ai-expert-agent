# chatbot_app/views.py

import os
from dotenv import load_dotenv
import datetime
import requests
import json
import time

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

import google.generativeai as genai

# The following import is no longer needed due to a library update
# from google.generativeai.types import FunctionResponse 

# Load the API keys from the .env file
load_dotenv()

# --- Gemini Agent Setup ---
gemini_api_key = os.getenv("GEMINI_API_KEY")
weatherapi_key = os.getenv("WEATHERAPI_KEY")

genai.configure(api_key=gemini_api_key)

# Define tool functions
def get_current_time():
    """
    Returns the current time in a human-readable format.
    """
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

def get_current_weather(city: str):
    """
    Returns the current weather for a given city using WeatherAPI.com.
    Args:
        city: The name of the city to get the weather for.
    """
    api_key = os.getenv("WEATHERAPI_KEY")
    base_url = "http://api.weatherapi.com/v1/current.json"
    complete_url = f"{base_url}?key={api_key}&q={city}"
    try:
        response = requests.get(complete_url)
        response.raise_for_status()
        data = response.json()
        if "error" not in data:
            current_data = data['current']
            temperature = f"{current_data['temp_c']}°C"
            condition = current_data['condition']['text']
            return {"temperature": temperature, "condition": condition}
        else:
            return {"error": data['error']['message']}
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to connect to the weather service: {e}"}
    except Exception as e:
        return {"error": f"An error occurred: {e}"}

# Tool declarations
time_tool_declaration = genai.protos.FunctionDeclaration(
    name='get_current_time',
    description='Returns the current time in a human-readable format.',
    parameters=genai.protos.Schema(type=genai.protos.Type.OBJECT, properties={})
)
weather_tool_declaration = genai.protos.FunctionDeclaration(
    name='get_current_weather',
    description='Returns the current weather for a specified city.',
    parameters=genai.protos.Schema(type=genai.protos.Type.OBJECT, properties={'city': genai.protos.Schema(type=genai.protos.Type.STRING, description='The name of the city to get the weather for.')}, required=['city'])
)

model = genai.GenerativeModel(
    'gemini-2.5-flash',
    system_instruction="""From now on, you are a friendly expert in Python programming. You answer my questions about code, best practices, and debugging. Keep your answers clear and concise. Do NOT answer questions that are not related to Python programming. You have access to a tool to get the current time and a tool to get the weather for a specific location.""",
    tools=[time_tool_declaration, weather_tool_declaration]
)

# In a web app, the chat history should be handled with user sessions.
# For simplicity, we'll maintain a single global chat session here.
chat = model.start_chat()

def get_gemini_response_with_memory(prompt):
    MAX_RETRIES = 5
    retry_count = 0
    delay = 1

    while retry_count < MAX_RETRIES:
        try:
            response = chat.send_message(prompt)
            while True:
                tool_responses = []
                response_text = ""
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            tool_call = part.function_call
                            tool_name = tool_call.name
                            tool_args = tool_call.args
                            if tool_name == 'get_current_time':
                                tool_output = get_current_time()
                                response_data = {'time': tool_output}
                            elif tool_name == 'get_current_weather':
                                tool_output = get_current_weather(**tool_args)
                                response_data = tool_output
                            else:
                                response_data = {"error": "Unknown tool."}
                            tool_responses.append(genai.protos.Part(function_response=genai.protos.FunctionResponse(name=tool_name, response=response_data)))
                        elif part.text:
                            response_text += part.text
                if response_text:
                    return response_text
                if tool_responses:
                    response = chat.send_message(genai.protos.Content(parts=tool_responses))
                else:
                    return "No text content was returned. This may be due to safety filters or an unexpected model response."
        except genai.types.BlockedPromptException as e:
            return f"An error occurred: The prompt was blocked due to safety concerns: {e}"
        except Exception as e:
            print(f"An error occurred on attempt {retry_count + 1}: {e}")
            if "429" in str(e) and retry_count < MAX_RETRIES - 1:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2
                retry_count += 1
            else:
                return f"An error occurred after multiple retries: {e}"
    return "An error occurred after multiple retries. The API call could not be completed."

# --- Django Views ---
def home(request):
    return render(request, 'chatbot_app/index.html')

@csrf_exempt
def chat_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_input = data.get('message')
            if not user_input:
                return JsonResponse({"error": "No message provided"}, status=400)
            
            ai_response = get_gemini_response_with_memory(user_input)
            return JsonResponse({"response": ai_response})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    return JsonResponse({"error": "Invalid request method"}, status=405)