from google.genai import types
import random
import smtplib
import random
import os
from email.message import EmailMessage
from services.logger import get_logger
from services.db_service import DBService
from dotenv import load_dotenv

import time



logger = get_logger()
db = DBService()


async def process_agent_response(event):
    """Process and return agent's final response text."""
    logger.info(f"process_agent_response: Event ID: {event.id}, Author: {event.author}")
    final_response = "Not able to process the request"
    if not event.content or not event.content.parts:
        logger.info("process_agent_response: No content parts in event")
        return None

    for idx, part in enumerate(event.content.parts):
        if hasattr(part, "text") and part.text and not part.text.isspace():
            logger.info(f"process_agent_response: Part {idx}: '{part.text.strip()}'")

    if event.is_final_response():
        for part in event.content.parts:
            if hasattr(part, "text") and part.text and not part.text.isspace():
                final_response = part.text.strip()
                logger.info("===================== AGENT FINAL RESPONSE ========================")
                logger.info(f"process_agent_response: {final_response}")
        return final_response

    return None



async def call_agent_async(runner, user_id, session_id, query):
    """Call the agent asynchronously with the user's query."""
    content = types.Content(role="user", parts=[types.Part(text=query)])
    
    final_response_text = None
    agent_name = None
    logger.info(f"call_agent_async: Query: {query}")
    try:
        logger.info(f"call_agent_async: user_id: {user_id}  session_id: {session_id}  content: {content}")
        async for event in runner.run_async(
            user_id=user_id, 
            session_id=session_id, 
            new_message=content,
            
        ):
            # Capture the agent name from the event if available
            logger.info(f"call_agent_async: Event: {vars(event)}")
            if event.author:
                agent_name = event.author
            logger.info(f"call_agent_async: user_id: Waiting response from agent: {agent_name}")
            response = await process_agent_response(event)
            logger.info(f"call_agent_async: Agent Response: {response}")
            if response:
                final_response_text = response
        return final_response_text
    except Exception as e:
        msg = f"ERROR during agent run: {e}"
        logger.info(msg)
        print(msg)
        return
    

#async def call_custom_async(runner, user_id, session_id, query):
async def call_custom_async(runner, state, user_id, session_id, pending_tool, pending_args, message):
    """Call the agent asynchronously with the user's query."""
    
    final_response_text = None
    agent_name = None
    logger.info(f"call_custom_async: Query: {message} and state {state}")
    try:

        new_message=types.Content(role="model",parts=[types.Part(function_call=types.FunctionCall(name=pending_tool,args=pending_args))])
        logger.info(f"call_custom_async: user_id: {user_id}  session_id: {session_id}  content: {new_message}")
        
                 
        async for event in runner.run_async(
            user_id=user_id, 
            session_id=session_id, 
            new_message=new_message,
            
        ):
            # Capture the agent name from the event if available
            logger.info(f"FULL EVENT DUMP: {event}")
            #logger.info(f"call_agent_async: Event: {vars(event)}")
            if event.author:
                agent_name = event.author
            logger.info(f"call_agent_async: user_id: Waiting response from agent: {agent_name}")
            response = await process_agent_response(event)
            logger.info(f"call_agent_async: Agent Response: {response}")
            if response:
                final_response_text = response
        return final_response_text
    except Exception as e:
        msg = f"ERROR during agent run: {e}"
        logger.info(msg)
        print(msg)
        return

        
    

def set_intent(message, session):
    '''
    Set the intent for account management based on user input.
    '''
    try:
        msg_lower = message.lower()
        session.state["intent"] = None

        if "update address" in msg_lower:
            session.state["intent"] = "update_address"
        elif "update email" in msg_lower:
            session.state["intent"] = "update_email"
        elif "update password" in msg_lower:
            session.state["intent"] = "update_password"
        elif "update contact" in msg_lower:
            session.state["intent"] = "update_contact"
        elif "create account" in msg_lower:
            session.state["intent"] = "create_account"

    except Exception as e:
        msg = f"ERROR int set_intent: {e}"
        print(msg)


def get_user_id():
    user_id = str(random.randint(1000, 9999))
    return user_id

def update_customer_data(user_details, customer):
    if user_details:
        customer.username = user_details.get('username', '')
        customer.password = user_details.get('password', '')
        customer.first_name = user_details.get('first_name', '')
        customer.last_name = user_details.get('last_name', '')
        customer.email = user_details.get('email', '')
        customer.new_contact = user_details.get('phone_number', '')
        customer.address = user_details.get('address', '')
    return customer


def send_otp(recipient_email, otp):
    logger.info(f"send_otp: Sending OTP to {recipient_email}")
    msg = EmailMessage()
    msg.set_content(f"Your OTP is: {otp}")
    msg['Subject'] = 'Your OTP for Account Verification'
    msg['From'] = os.getenv("EMAIL_SENDER")
    msg['To'] = recipient_email
    
    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
        server.starttls()
        server.login(os.getenv("EMAIL_SENDER"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)
    logger.info(f"send_otp: Sending OTP with message  {msg}")
    return 


def get_instruction():
    
    instruction="""
        You are an Account Manager service agent. You help users with tools:
        - create_account : creates user account
        - update_password : update user password
        - update_email : update user email
        - update_contact: update contact
        - update_address : update address
        List the tool details to user to choose the correct tool.
        if state["otp_status"] is None, then assume that all OTP related task has either not started or is over. 
            - Dont prompt again the OTP verification failed after every input of user
            Then only Dont ask for OTP if state.otp_status is not OTP_PENDING
        
        """
    logger.info(f"Instruction {instruction}")
    return instruction


def verify_otp(state, user_otp_input, tool_name):
    """
    Verifies the OTP for a given username using session state.
    Returns a structured response indicating next action.
    """
    customer = state.get("customer", {})
    
    username = customer.username
    logger.info(f"verify_otp for {username} and state {state}")

    
    # Check OTP expiration
    #timestamp = otp_info.get("timestamp")
    #if not timestamp or time.datetime.now() > timestamp + time.timedelta(minutes=otp_expiry_minutes):
    #   logger.info(f"OTP for {username} expired.")
    #    state.pop(username, None)
    #    return {
    #        "status": "AUTH_REQUIRED",
    #        "message": "Your OTP has expired. Please start authentication again."
    #    }

    # Check user input
    generated_otp = state["generated_otp"]
    logger.info(f"verify_otp:  for generated_otp={generated_otp} and user_otp_input={user_otp_input}")
    
    if user_otp_input != generated_otp:
        return {
            "status": "OTP_PENDING",
            "message": "Invalid OTP. Please try again."
        }

    # OTP verified successfully
    logger.info(f"OTP for {username} verified successfully.")
    state.pop(username, None)
    state["otp_status"] = "OPT_VERIFIED_SUCCESS"
    
    return {
        "status": "OPT_VERIFIED_SUCCESS",
        "message": f"OTP verified. Proceeding with {tool_name}.",
    }


def update_customer_account(state: dict) -> str:
    tool_name = state["pending_tool"]
    pending_args = state["pending_args"]
    
    if tool_name == "update_contact":
        new_phone_number = pending_args.get("new_phone_number", None)
        if new_phone_number is None:
            return False
        username = pending_args.get("username", None)
        try:
            logger.info(f"Attempting to update phone number for {username}.")
            # Corrected field name from "contact" to "phone_number" to match create_account
            status = db.update_field(username, "phone_number", new_phone_number)
            if status:
                logger.info(f"Successfully updated phone number for {username}.")

                    # Update Customer
                customer = state.get("customer")
                customer.new_contact = new_phone_number
                state["customer"] = customer
                return f"Phone number updated successfully for {username}."
        
            return f"Failed to update phone number for {username}."
        except Exception as e:
            logger.error(f"Failed to update phone number for {username}: {e}", exc_info=True)
            return f"Failed to update phone number for {username}: {str(e)}"

        
    elif tool_name == "update_password":
        #new_password
        
        new_password = pending_args.get("new_password", None)
        if new_password is None:
            return False
        username = pending_args.get("username", None)
        try:
            logger.info(f"Attempting to update password for {username}.")
            # Corrected field name from "contact" to "phone_number" to match create_account
            status = db.update_field(username, "password", new_password)
            if status:
                logger.info(f"Successfully updated password for {username}.")

                    # Update Customer
                customer = state.get("customer")
                customer.password = new_password
                state["customer"] = customer
                return f"Password updated successfully for {username}."
        
            return f"Failed to update password for {username}."
        except Exception as e:
            logger.error(f"Failed to update password for {username}: {e}", exc_info=True)
            return f"Failed to update password for {username}: {str(e)}"
    elif tool_name == "update_email":
        #new_email
        new_email = pending_args.get("new_email", None)
        if new_email is None:
            return False
        username = pending_args.get("username", None)
        try:
            logger.info(f"Attempting to update email for {username}.")
            # Corrected field name from "contact" to "phone_number" to match create_account
            status = db.update_field(username, "email", new_email)
            if status:
                logger.info(f"Successfully updated email for {username}.")

                    # Update Customer
                customer = state.get("customer")
                customer.email = new_password
                state["customer"] = customer
                return f"email updated successfully for {username}."
        
            return f"Failed to update email for {username}."
        except Exception as e:
            logger.error(f"Failed to update email for {username}: {e}", exc_info=True)
            return f"Failed to update email for {username}: {str(e)}"
    elif tool_name == "update_address":
        #new_address
        new_address = pending_args.get("new_address", None)
        if new_address is None:
            return False
        username = pending_args.get("username", None)
        try:
            logger.info(f"Attempting to update address for {username}.")
            # Corrected field name from "contact" to "phone_number" to match create_account
            status = db.update_field(username, "address", new_address)
            if status:
                logger.info(f"Successfully updated address for {username}.")

                    # Update Customer
                customer = state.get("customer")
                customer.address = new_address
                state["customer"] = customer
                return f"Address updated successfully for {username}."
        
            return f"Failed to update address for {username}."
        except Exception as e:
            logger.error(f"Failed to update address for {username}: {e}", exc_info=True)
            return f"Failed to update address for {username}: {str(e)}"
    return True

'''
async def persist_cleared_state(session_service, session, app_name, user_id, session_id):
    cleared_delta = {
        "pending_tool": None,
        "pending_args": None,
        "otp_status": None,
        "generated_otp": None,
        "otp_timestamp": None,
        "conversation": get_instruction()
    }

    event = Event(
        invocation_id="manual-clear",
        author="system",
        timestamp=time.time(),
        actions=EventActions(state_delta=cleared_delta)
    )

    await session_service.append_event(session, event)
    '''

def reset_state(state):
    state["pending_tool"] = None
    state["pending_args"] = None
    state["otp_status"] = None
    state["generated_otp"] = None
    state["otp_timestamp"] = None
    return state


    

   
