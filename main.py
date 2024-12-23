from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
import openai
import elevenlabs

# Directly use API keys
OPENAI_API_KEY = ""
ELEVENLABS_API_KEY = ""
TWILIO_ACCOUNT_SID = ""
TWILIO_AUTH_TOKEN = ""
TWILIO_PHONE_NUMBER = ""
BASE_URL = ""

# Set API keys
openai.api_key = OPENAI_API_KEY
elevenlabs.api_key = ELEVENLABS_API_KEY
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Initialize FastAPI app
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conversation state management
class ConversationManager:
    def __init__(self):
        self.conversations = {}
    
    def get_or_create_conversation(self, call_sid):
        if call_sid not in self.conversations:
            self.conversations[call_sid] = {
                'messages': [
                    {
                        "role": "system",
                        "content": """
                        You are a professional sales agent for Cleaning LLC. 
                        Your goal is to:
                        1. Engage the potential customer in a friendly conversation
                        2. Explain residential cleaning services
                        3. Gather contact and interest information
                        4. Offer a progressive discount (max 15%)
                        
                        Service Pricing:
                        - Studio + Bath: $140.00 (2 hours)
                        - 1 Bedroom + 1 Bath: $180.00 (2.5 hours)
                        - 2 Bedroom + 2 Bath: $220.00 (3 hours)
                        
                        Approach:
                        - Be conversational and empathetic
                        - Listen to customer needs
                        - Provide clear value proposition
                        - Handle objections professionally
                        """
                    },
                    {
                        "role": "assistant",
                        "content": "Hello! This is Sarah from Cleaning LLC. How are you doing today?"
                    }
                ]
            }
        return self.conversations[call_sid]

conversation_manager = ConversationManager()

def get_ai_response(call_sid, user_input):
    """Generate AI response for the conversation"""
    conversation = conversation_manager.get_or_create_conversation(call_sid)
    
    # Add user input to conversation
    conversation['messages'].append({
        "role": "user",
        "content": user_input
    })
    
    # Generate AI response using OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-16k",
        temperature=0.7,
        messages=conversation['messages']
    )
    
    ai_response = response.choices[0].message["content"]
    
    # Add AI response to conversation
    conversation['messages'].append({
        "role": "assistant",
        "content": ai_response
    })
    
    return ai_response

def generate_ai_speech(text, voice="Sarah"):
    """Convert AI text response to speech using ElevenLabs with detailed error logging"""
    try:
        print(f"Generating speech for text: {text}")
        
        # Ensure ElevenLabs API key is set
        if not elevenlabs.api_key:
            raise ValueError("ElevenLabs API key is missing!")

        # Attempt to generate speech
        audio = elevenlabs.generate(
            text=text,
            voice=voice,
            model="eleven_multilingual_v2"
        )
        print("Speech generation successful.")
        return audio

    except Exception as e:
        # Log detailed errors for debugging
        print(f"Speech generation error: {e}")
        return None

@app.post("/twilio/voice/incoming")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice call"""
    form_data = await request.form()
    call_sid = form_data.get('CallSid')

    response = VoiceResponse()

    try:
        conversation = conversation_manager.get_or_create_conversation(call_sid)
        initial_greeting = conversation['messages'][1]['content']

        speech_audio = generate_ai_speech(initial_greeting)
        if speech_audio:
            temp_audio_path = f"/tmp/{call_sid}_greeting.mp3"
            with open(temp_audio_path, 'wb') as f:
                f.write(speech_audio)
            response.play(temp_audio_path)
        else:
            response.say(initial_greeting)

        gather = response.gather(
            input='speech', 
            speechTimeout='auto',
            action='/twilio/voice/handle-speech',
            method='POST'
        )
        gather.say("Please speak after the tone.")
        response.redirect('/twilio/voice/incoming')

    except Exception as e:
        print(f"Error handling incoming call: {e}")
        response.say(f"Sorry, there was an error processing the call.")
    
    return Response(content=str(response), media_type="application/xml")

@app.post("/twilio/voice/handle-speech")
async def handle_speech(request: Request):
    """Process user speech input"""
    form_data = await request.form()
    call_sid = form_data.get('CallSid')
    speech_result = form_data.get('SpeechResult', '')

    response = VoiceResponse()

    try:
        ai_response = get_ai_response(call_sid, speech_result)
        speech_audio = generate_ai_speech(ai_response)

        if speech_audio:
            temp_audio_path = f"/tmp/{call_sid}_response.mp3"
            with open(temp_audio_path, 'wb') as f:
                f.write(speech_audio)
            response.play(temp_audio_path)
        else:
            response.say(ai_response)

        gather = response.gather(
            input='speech', 
            speechTimeout='auto',
            action='/twilio/voice/handle-speech',
            method='POST'
        )
        gather.say("Please continue.")

    except Exception as e:
        print(f"Error processing speech input: {e}")
        response.say(f"Sorry, there was an error processing your response.")

    return Response(content=str(response), media_type="application/xml")

@app.post("/make-call")
async def make_outbound_call(phone_number: str):
    """Initiate an outbound call to a phone number"""
    try:
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/twilio/voice/incoming"
        )
        return {"message": "Call initiated", "call_sid": call.sid}
    except Exception as e:
        print(f"Error initiating call: {e}")
        return {"error": str(e)} 