import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("email-service")

def send_confirmation_email(to_email: str, name: str, service: str, date: str, time: str, vehicle_info: str):
    """
    Sends a simple confirmation email with appointment details.
    Does not include ICS or meeting links.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not sender_email or not sender_password:
        logger.warning("SMTP credentials (SMTP_SENDER_EMAIL, SMTP_PASSWORD) not found in environment. Email not sent.")
        return False

    subject = "Appointment Confirmation - Partners Motors"
    
    body = f"""Dear {name},

We have successfully scheduled your appointment.

Details:
Service: {service}
Date: {date}
Time: {time}
Vehicle: {vehicle_info}

Thank you for choosing Partners Motors.
"""

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def send_waitlist_email(to_email: str, name: str, vehicle_info: str):
    """
    Sends a waitlist confirmation email.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not sender_email or not sender_password:
        logger.warning("SMTP credentials not found. Email not sent.")
        return False

    subject = "Vehicle Waitlist Confirmation - Partners Motors"
    
    body = f"""Dear {name},

You have been added to our waitlist for the following vehicle:
{vehicle_info}

We will notify you immediately via email or phone as soon as it becomes available.

Best regards,
Partners Motors Sales Team
"""

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        logger.info(f"Waitlist email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send waitlist email: {e}")
        return False
