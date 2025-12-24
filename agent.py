import logging
import os
import asyncio
import re
from typing import Annotated, AsyncIterable, Any
from dotenv import load_dotenv

from livekit import rtc, agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    function_tool,
    AgentTask,
)
from livekit.agents.beta.workflows import TaskGroup
from livekit.plugins import openai, deepgram, silero, google

# Ensure email_service.py is in the same folder
from email_service import send_confirmation_email, send_waitlist_email

load_dotenv(".env.local")
logger = logging.getLogger("partners-motors-sales")

# --- 🚗 DUMMY INVENTORY ---
INVENTORY = [
    {"make": "toyota", "model": "camry", "year": 2023},
    {"make": "tesla", "model": "model 3", "year": 2024},
    {"make": "honda", "model": "civic", "year": 2012}, 
    {"make": "honda", "model": "civic", "year": 2022},
]

# --- 📧 CUSTOM EMAIL TASK (From Lena) ---
class GetEmailTask(AgentTask[str]):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions="""
            Ask the user for their email address to send the confirmation.
            1. If they provide it, VALIDATE it has an '@' symbol.
            2. If they say "skip" or "no", confirm they want to proceed without email.
            3. If the email is invalid, ask them to repeat it clearly.
            """,
            chat_ctx=chat_ctx,
        )
        self.email = None

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Ask: 'Could you please share your email address so I can send you the confirmation?'"
        )

    @function_tool()
    async def save_email(self, email: str) -> str:
        """Call this when the user says their email address."""
        # Clean up common voice-to-text errors
        cleaned_email = email.lower().replace(" at ", "@").replace(" dot ", ".").replace(" ", "")
        
        if "@" not in cleaned_email or "." not in cleaned_email:
            return "That didn't sound like a valid email. Please ask the user to repeat it."
        
        self.email = cleaned_email
        
        # Format for TTS pronunciation
        spoken_email = cleaned_email.replace('.', ' dot ').replace('@', ' at ')
        
        return f"Email captured: {cleaned_email}. Confirm by saying: 'Just to check, is that {spoken_email}?'"

    @function_tool()
    async def confirm_email(self) -> None:
        """Call this when the user says 'Yes' to the email confirmation."""
        if self.email:
            self.complete(self.email)

    @function_tool()
    async def skip_email(self) -> None:
        """Call this if the user refuses to give an email."""
        self.complete("unknown")

# --- 🧠 AGENT ---
class PartnersMotorsAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
            You are Jamie, a very friendly, warm, and enthusiastic sales agent for Partners Motors. 
            
            STRICT VOICE RULES:
            1. ONLY speak dialogue meant for the customer.
            2. NEVER speak internal thoughts or JSON.
            3. NEVER say "I will check the inventory". Call the tool SILENTLY.
            
            WORKFLOW (MUST BE STEP-BY-STEP - ONE QUESTION AT A TIME):
            1. **Greeting:** Welcome the user with high energy! Ask what they are excited to buy today.
            2. **Clarify Make & Model:** If vague, hype up a suggestion or ask for specifics.
            3. **Check Inventory:** Call `check_inventory`.
            
            4. **IF IN STOCK:
               - **Assumptive Close:** "Yes!! Great news! We have that exact car! It's stunning. You're going to love it. Let's get you in the driver's seat—does tomorrow work for a test drive, or is the weekend better?"
               - [Wait for answer regarding Date/Time]
               - Ask for **Full Name**.
               - [Wait for answer]
               - **VERIFY NAME:** "Got it! Just to be safe, did I get that right? Is it [Name]? Let me spell that out: [S-P-E-L-L  O-U-T  L-E-T-T-E-R-S]. Is that correct?"
               - [Wait for confirmation. If wrong, correct it.]
               - Ask for **Email Address**.
               - [Wait for answer]
               - **VERIFY EMAIL:** "Awesome. And just to be 100% sure on the email, that's [Email] — let me spell that out: [S-P-E-L-L  O-U-T  L-E-T-T-E-R-S]. Is that correct?"
               - [Wait for explicit 'Yes'. If 'No', ask again.]
               - Call `book_appointment`.

            5. **IF OUT OF STOCK:
               - Empathize. "Oh no... I'm so sorry, we don't have that exact one right this second."
               - Pivot to help: "But I can track one down for you! What's your budget and max mileage so I can find the perfect match?"
               - [Wait for answer]
               - Ask for **Full Name**.
               - [Wait for answer]
               - **VERIFY NAME:** "Got it! Just to be safe, did I get that right? Is it [Name]? Let me spell that out: [S-P-E-L-L  O-U-T  L-E-T-T-E-R-S]. Is that correct?"
               - [Wait for confirmation. If wrong, correct it.]
               - Ask for **Email Address**.
               - [Wait for answer]
               - **VERIFY EMAIL:** "Awesome. And just to be 100% sure on the email, that's [Email] — let me spell that out: [S-P-E-L-L  O-U-T  L-E-T-T-E-R-S]. Is that correct?"
               - [Wait for explicit 'Yes'. If 'No', ask again.]
               - Call `add_to_waitlist`.
            """,
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions="Say: 'Hey there! Welcome to Partners Motors. I'm Jamie! What kind of car are you dreaming to buy today?'"
        )

    # --- 🗣️ TTS OVERRIDE (From Lena) ---
    # This ensures emails are pronounced "dot com" instead of ignored punctuation
    async def tts_node(self, text: AsyncIterable[str], model_settings: Any) -> AsyncIterable[rtc.AudioFrame]:
        async def convert_email_to_speech(input_text: AsyncIterable[str]) -> AsyncIterable[str]:
            async for chunk in input_text:
                modified_chunk = chunk
                # Regex to find emails and replace symbols with words
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                def replace_email(match):
                    email = match.group(0)
                    spoken = email.replace('.', ' dot ').replace('@', ' at ')
                    return spoken
                
                modified_chunk = re.sub(email_pattern, replace_email, modified_chunk)
                yield modified_chunk

        async for frame in Agent.default.tts_node(self, convert_email_to_speech(text), model_settings):
            yield frame

    @function_tool
    async def check_inventory(
        self, 
        make: Annotated[str, "The car manufacturer"], 
        model: Annotated[str, "The car model"], 
        year: Annotated[int | str | None, "The specific year"] = None
    ) -> str:
        """Check if a specific car is currently in our stock."""
        if year and isinstance(year, str):
            year = int(year) if year.isdigit() else None
        
        logger.info(f"Checking inventory: {year} {make} {model}")
        
        matches = [c for c in INVENTORY if c['make'].lower() == make.lower() and c['model'].lower() == model.lower()]
        if year:
            matches = [c for c in matches if c['year'] == year]

        if matches:
            return f"MATCH_FOUND: We have it! Ask for their Name and preferred Appointment Time."
        
        return f"NOT_FOUND: We don't have that specific one. Ask for their Name, Budget, and Max Mileage so I can waitlist them."

    @function_tool
    async def process_appointment(
        self, 
        first_name: str, 
        last_name: str, 
        make: str, 
        model: str, 
        year: str, 
        date: str, 
        time: str
    ) -> str:
        """
        Call this when the user agrees to book an appointment. 
        This triggers the EMAIL COLLECTION sub-task.
        """
        
        # 1. Trigger the Email Task (From Lena)
        email_task = GetEmailTask(chat_ctx=self.chat_ctx)
        user_email = await email_task.run() # This waits for the user to answer the email questions

        if user_email == "unknown":
            return "Appointment booked, but user skipped email confirmation."

        # 2. Send the email
        car_details = f"{year} {make} {model}"
        full_name = f"{first_name} {last_name}"
        
        print(f"DEBUG: Sending confirmation to {user_email}...") 
        success = await asyncio.to_thread(send_confirmation_email, user_email, full_name, "Test Drive", date, time, car_details)
        
        return "SUCCESS: Appointment confirmed and email sent!" if success else "ERROR: Email failed to send."

    @function_tool
    async def process_waitlist(
        self, 
        first_name: str, 
        last_name: str, 
        make: str, 
        model: str, 
        year: str, 
        mileage: str, 
        budget: str
    ) -> str:
        """
        Call this when adding a user to the waitlist.
        This triggers the EMAIL COLLECTION sub-task.
        """
        
        # 1. Trigger the Email Task (From Lena)
        email_task = GetEmailTask(chat_ctx=self.chat_ctx)
        user_email = await email_task.run()

        if user_email == "unknown":
            return "User added to waitlist, but skipped email."

        # 2. Send the email
        full_name = f"{first_name} {last_name}"
        car_details = f"{year} {make} {model} (Max Mileage: {mileage}, Budget: {budget})"
        
        print(f"DEBUG: Sending waitlist email to {user_email}...")
        success = await asyncio.to_thread(send_waitlist_email, user_email, full_name, car_details)
        
        return "SUCCESS: Added to waitlist and email sent!" if success else "ERROR: Email failed to send."

# --- 🚀 SERVER ---
server = AgentServer()

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=google.LLM(model="gemini-3-flash-preview"),
        tts=deepgram.TTS(),
    )

    await session.start(agent=PartnersMotorsAgent(), room=ctx.room)

if __name__ == "__main__":
    agents.cli.run_app(server)          