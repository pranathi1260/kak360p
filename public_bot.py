import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
import googlemaps
import math

from config import config
from utils.ai_helper import GeminiAI
from utils.pdf_generator import create_complaint_pdf, create_rti_pdf
from database.db_setup import init_database, save_complaint, save_rti_request, save_traffic_violation
from utils.otp_service import OTPService

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize AI
ai = GeminiAI()

# Initialize database
init_database()

# Ensure storage directories exist
for directory in (
    config.COMPLAINTS_DIR,
    config.RTI_DIR,
    config.TRAFFIC_DIR,
    config.AADHAAR_COMPLAINT_DIR,
    config.AADHAAR_RTI_DIR,
):
    os.makedirs(directory, exist_ok=True)

# Conversation states
# Complaint flow
(
    COMPLAINT_NAME,
    COMPLAINT_FATHER_NAME,
    COMPLAINT_AGE,
    COMPLAINT_PHONE,
    COMPLAINT_OTP,
    COMPLAINT_EMAIL,
    COMPLAINT_AADHAAR,
    COMPLAINT_ADDRESS,
    COMPLAINT_INITIAL_DESC,
    COMPLAINT_TYPE,
    COMPLAINT_DATE,
    COMPLAINT_LOCATION,
    COMPLAINT_DESCRIPTION,
) = range(13)

# RTI flow
(
    RTI_NAME,
    RTI_PHONE,
    RTI_OTP,
    RTI_EMAIL,
    RTI_AADHAAR,
    RTI_ADDRESS,
    RTI_DEPARTMENT,
    RTI_INFO,
    RTI_PURPOSE,
) = range(20, 29)

# Traffic violation flow
(
    TRAFFIC_NAME,
    TRAFFIC_PHONE,
    TRAFFIC_OTP,
    TRAFFIC_VEHICLE,
    TRAFFIC_TYPE,
    TRAFFIC_LOCATION,
    TRAFFIC_PHOTO,
    TRAFFIC_DESC,
) = range(30, 38)

# OTP service
otp_service = OTPService()


def normalize_phone_number(raw_phone: str) -> str:
    """Convert phone number to E.164 (default +91 if 10 digits)."""
    phone = raw_phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if phone.startswith("00"):
        phone = phone[2:]
    if phone.startswith("0"):
        phone = phone[1:]
    if len(phone) == 10 and phone.isdigit():
        return "+91" + phone
    if not phone.startswith("+"):
        return "+" + phone
    return phone


# ============== START & HELP COMMANDS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_message = """🙏 Namaste! Welcome to Kakinada AI Legal Assistant 🏛️

🌟 *Powered by Gemini AI with Real-time Google Search*

*Current Government (2025):*
• CM: N. Chandrababu Naidu (TDP-led NDA)
• Key Schemes: Annadata Sukhibhava, Talliki Vandanam, Health Insurance

*What I Can Help With:*
📚 Legal Information & Advice (Latest Laws)
⚖️ Indian Laws & Rights
🏛️ Government Schemes (Real-time)
📝 Complaint/FIR Filing
📄 RTI Application Filing
🚗 Traffic Violation Reporting (NEW!)
📍 Police Station Locations
🔍 Document Analysis

*Quick Commands:*
/help - All commands
/complaint - File complaint/FIR
/rti - File RTI application
/traffic - Report traffic violation
/police - Police stations

💬 Ask me anything legal!
📸 Send images/documents for analysis"""

    keyboard = [
        [InlineKeyboardButton("📝 File Complaint", callback_data='start_complaint')],
        [InlineKeyboardButton("📄 File RTI", callback_data='start_rti')],
        [InlineKeyboardButton("🚗 Report Traffic Violation", callback_data='start_traffic')],
        [InlineKeyboardButton("📍 Police Stations", callback_data='police_stations')],
        [InlineKeyboardButton("🏛️ Gov Schemes", callback_data='gov_schemes'),
         InlineKeyboardButton("⚖️ Legal Info", callback_data='legal_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """🔍 *Kakinada AI Legal Assistant - Help*

*Commands:*
/start - Start the bot
/help - Show this help
/complaint - File complaint/FIR
/rti - File RTI application
/traffic - Report traffic violation
/police - Find police stations
/schemes - Government schemes
/laws - Legal information
/cancel - Cancel operation

*Features:*
✅ Real-time legal information (Google Search)
✅ Latest government schemes
✅ Complaint/FIR filing with PDF
✅ RTI application with PDF
✅ Traffic violation reporting (with photo)
✅ Nearest police stations (GPS-based)
✅ Document & image analysis
✅ Applicable law sections

*How to Use:*
• Type your legal question
• Use commands for specific actions
• Send location for nearby police stations
• Upload photos for traffic violations
• Upload documents for analysis

*Emergency:*
🚨 Police: 100
🆘 Emergency: 112
👮 Women Helpline: 181
👶 Child Helpline: 1098"""

    await update.message.reply_text(help_text, parse_mode='Markdown')


# ============== BUTTON HANDLERS ==============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'start_complaint':
        await query.message.reply_text("📝 Starting complaint filing...\n\nUse /complaint command to begin")
    elif query.data == 'start_rti':
        await query.message.reply_text("📄 Starting RTI application...\n\nUse /rti command to begin")
    elif query.data == 'start_traffic':
        await query.message.reply_text("🚗 Starting traffic violation report...\n\nUse /traffic command to begin")
    elif query.data == 'police_stations':
        await police_stations(query, context, is_callback=True)
    elif query.data == 'gov_schemes':
        await schemes_callback(query, context)
    elif query.data == 'legal_info':
        await laws_callback(query, context)


# ============== POLICE STATIONS ==============
async def police_stations(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    """Show nearest police stations - request location"""
    location_button = KeyboardButton(text="📍 Share My Location", request_location=True)
    keyboard = ReplyKeyboardMarkup([[location_button], ["❌ Cancel"]], one_time_keyboard=True, resize_keyboard=True)
    
    response = """📍 *Find Nearest Police Stations*

To show you the nearest police stations, I need your current location.

👇 Click the button below to share your location, or type your city/area name.

_Your location is used only to find nearby police stations and is not stored._"""
    
    if is_callback:
        await update.message.reply_text(response, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(response, parse_mode='Markdown', reply_markup=keyboard)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle location shared by user"""
    location = update.message.location
    if not location:
        await update.message.reply_text("❌ Location not received. Please try again.", reply_markup=ReplyKeyboardRemove())
        return
    
    latitude = location.latitude
    longitude = location.longitude
    
    await update.message.reply_text("📍 Location received!\n🔍 Searching for nearest police stations...", reply_markup=ReplyKeyboardRemove())
    
    try:
        gmaps = googlemaps.Client(key=config.GOOGLE_MAPS_API_KEY)
        places_result = gmaps.places_nearby(
            location=(latitude, longitude),
            radius=5000,
            type='police',
            keyword='police station'
        )
        
        if not places_result.get('results'):
            await update.message.reply_text(
                "❌ No police stations found near your location.\n\n"
                "📞 Emergency: 100 | 112",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        police_stations_list = places_result['results'][:3]
        
        def calculate_distance(lat1, lon1, lat2, lon2):
            R = 6371
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1)
            delta_lon = math.radians(lon2 - lon1)
            a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return round(R * c, 2)
        
        response_parts = ["📍 *Nearest Police Stations:*\n"]
        
        for idx, station in enumerate(police_stations_list, 1):
            name = station.get('name', 'Unknown')
            address = station.get('vicinity', 'Address not available')
            
            station_lat = station['geometry']['location']['lat']
            station_lon = station['geometry']['location']['lng']
            distance = calculate_distance(latitude, longitude, station_lat, station_lon)
            
            station_info = f"\n{idx}. *{name}*\n📍 {address}\n🚗 Distance: {distance} km\n"
            response_parts.append(station_info)
        
        response_parts.append("\n🚨 *Emergency Numbers:*\n📞 Police: 100 | 🆘 Emergency: 112")
        
        await update.message.reply_text("".join(response_parts), parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error finding police stations: {e}")
        await update.message.reply_text(
            "❌ Error finding police stations.\n\n📞 Emergency: 100 | 112",
            reply_markup=ReplyKeyboardRemove()
        )


# ============== COMPLAINT FILING ==============
async def complaint_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start complaint filing"""
    await update.message.reply_text(
        "📝 *Complaint Filing Assistant*\n\n"
        "I'll help you prepare a complaint/FIR. Please answer the following questions.\n\n"
        "What is your *full name*?",
        parse_mode='Markdown'
    )
    context.user_data['complaint'] = {
        'user_id': update.message.from_user.id,
        'aadhaar_photo_path': None,
        'otp_attempts': 0,
    }
    return COMPLAINT_NAME


async def complaint_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['name'] = update.message.text
    await update.message.reply_text("What is your *Father's/Husband's name*?", parse_mode='Markdown')
    return COMPLAINT_FATHER_NAME


async def complaint_father_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['father_name'] = update.message.text
    await update.message.reply_text("What is your *age*?", parse_mode='Markdown')
    return COMPLAINT_AGE


async def complaint_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['age'] = update.message.text
    await update.message.reply_text("What is your *phone number*?", parse_mode='Markdown')
    return COMPLAINT_PHONE


async def complaint_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text
    phone = normalize_phone_number(raw_phone)
    context.user_data['complaint']['phone'] = phone

    if otp_service.send_otp(phone):
        context.user_data['complaint']['otp_attempts'] = 0
        await update.message.reply_text(
            f"📲 OTP sent to `{phone}`. Please enter the 6-digit code.",
            parse_mode='Markdown'
        )
        return COMPLAINT_OTP

    await update.message.reply_text(
        "❌ I couldn't send an OTP. Please check the number and enter it again.",
        parse_mode='Markdown'
    )
    return COMPLAINT_PHONE


async def complaint_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    complaint_data = context.user_data['complaint']
    phone = complaint_data['phone']

    if code.lower() == "resend":
        if otp_service.send_otp(phone):
            await update.message.reply_text(
                f"🔁 New OTP sent to `{phone}`. Enter the code.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Couldn't resend OTP. Please try again later.",
                parse_mode='Markdown'
            )
        return COMPLAINT_OTP

    attempts = complaint_data.get('otp_attempts', 0) + 1
    complaint_data['otp_attempts'] = attempts

    if otp_service.verify_otp(phone, code):
        await update.message.reply_text(
            "✅ Phone verified successfully!\n\nWhat is your *email address*? (Type 'skip' to skip)",
            parse_mode='Markdown'
        )
        return COMPLAINT_EMAIL

    if attempts >= 3:
        await update.message.reply_text(
            "❌ OTP verification failed multiple times. Please /complaint to restart.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "❌ Incorrect OTP. Try again or type *resend* for a new code.",
        parse_mode='Markdown'
    )
    return COMPLAINT_OTP


async def complaint_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if email.lower() != 'skip':
        context.user_data['complaint']['email'] = email
    
    await update.message.reply_text(
        "📎 Please *upload a clear photo of your Aadhaar card* to verify your application.\n\n"
        "• Tap the attachment icon and choose the Aadhaar image\n"
        "• Make sure your name and number are visible\n"
        "• Type 'cancel' to stop the process",
        parse_mode='Markdown'
    )
    return COMPLAINT_AADHAAR


async def complaint_aadhaar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    complaint_data = context.user_data['complaint']
    message = update.message

    if message.text:
        if message.text.lower() == 'cancel':
            await update.message.reply_text("❌ Complaint filing cancelled.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        await update.message.reply_text(
            "⚠️ Aadhaar photo is required to verify the genuineness of your complaint.\n"
            "Please upload a clear image of your Aadhaar card.",
            parse_mode='Markdown'
        )
        return COMPLAINT_AADHAAR

    file = None
    filename_suffix = "jpg"

    if message.photo:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        filename_suffix = "jpg"
    elif message.document:
        doc = message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await update.message.reply_text(
                "⚠️ Please upload the Aadhaar *as an image file* (jpg/png).",
                parse_mode='Markdown'
            )
            return COMPLAINT_AADHAAR
        file = await context.bot.get_file(doc.file_id)
        filename_suffix = (os.path.splitext(doc.file_name or "")[1].lstrip(".") or "jpg").lower()
    else:
        await update.message.reply_text(
            "⚠️ Please upload the Aadhaar *as an image file*.",
            parse_mode='Markdown'
        )
        return COMPLAINT_AADHAAR

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    aadhaar_dir = config.AADHAAR_COMPLAINT_DIR
    os.makedirs(aadhaar_dir, exist_ok=True)
    filename = f"aadhaar_complaint_{update.message.from_user.id}_{timestamp}.{filename_suffix}"
    file_path = os.path.join(aadhaar_dir, filename)

    await file.download_to_drive(file_path)
    complaint_data['aadhaar_photo_path'] = file_path

    await update.message.reply_text(
        "✅ Aadhaar card received.\n\n"
        "Now, please provide your *complete address*:\n"
        "House/Street, Village/Town, Mandal, District.",
        parse_mode='Markdown'
    )
    return COMPLAINT_ADDRESS


async def complaint_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['address'] = update.message.text
    await update.message.reply_text(
        "*Describe what happened:*\n\n"
        "Explain the incident in your own words. The AI will understand and suggest the complaint type.",
        parse_mode='Markdown'
    )
    return COMPLAINT_INITIAL_DESC


async def complaint_initial_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text
    context.user_data['complaint']['initial_description'] = description
    
    await update.message.reply_text("🤔 Analyzing your complaint...", parse_mode='Markdown')
    
    try:
        analysis_prompt = f"""Based on this incident, identify the complaint type:
"{description}"

Respond with ONLY the complaint type (e.g., Theft, Fraud, Harassment, Cyber Crime, etc.)"""
        
        user_id = update.message.from_user.id
        complaint_type = ai.send_message(user_id, analysis_prompt).strip()
        context.user_data['complaint']['suggested_type'] = complaint_type
        
        await update.message.reply_text(
            f"✅ I understand this is about:\n\n"
            f"📋 *{complaint_type}*\n\n"
            f"Is this correct?\n"
            f"• Type 'yes' to confirm\n"
            f"• Type the correct complaint type\n"
            f"• Type 'skip' if not sure",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error analyzing complaint: {e}")
        await update.message.reply_text("What *type of complaint* is this? (e.g., Theft, Fraud, Harassment)", parse_mode='Markdown')
    
    return COMPLAINT_TYPE


async def complaint_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    if user_input.lower() in ['yes', 'correct', 'ok', 'y']:
        complaint_type = context.user_data['complaint'].get('suggested_type', user_input)
    elif user_input.lower() == 'skip':
        complaint_type = "General Complaint"
    else:
        complaint_type = user_input
    
    context.user_data['complaint']['complaint_type'] = complaint_type
    await update.message.reply_text("*When did the incident occur?* (Date and time)", parse_mode='Markdown')
    return COMPLAINT_DATE


async def complaint_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['incident_date'] = update.message.text
    await update.message.reply_text(
        "*Where did the incident occur?* (Location/Address)\n\n"
        "Include: Area/Landmark, City/Village, Mandal, District",
        parse_mode='Markdown'
    )
    return COMPLAINT_LOCATION


async def complaint_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complaint']['incident_location'] = update.message.text
    await update.message.reply_text(
        "Any *additional details*? (Witnesses, evidence, sequence of events)\n\n"
        "Or type 'no' to skip",
        parse_mode='Markdown'
    )
    return COMPLAINT_DESCRIPTION


async def complaint_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    additional = update.message.text
    
    initial_desc = context.user_data['complaint'].get('initial_description', '')
    if additional.lower() in ['no', 'skip', 'none']:
        final_description = initial_desc
    else:
        final_description = f"{initial_desc}\n\nAdditional Details: {additional}"
    
    context.user_data['complaint']['description'] = final_description
    
    await update.message.reply_text("⏳ Processing your complaint... Please wait.")
    
    complaint_data = context.user_data['complaint']
    complaint_type = complaint_data.get('complaint_type', 'General Complaint')
    
    # Get applicable laws
    applicable_laws = ai.get_applicable_laws(complaint_type, final_description)
    complaint_data['applicable_laws'] = applicable_laws
    
    # Get police station info
    incident_location = complaint_data['incident_location']
    complaint_data['police_station'] = f"Nearest Police Station in {incident_location}"
    
    # Generate PDF
    try:
        filename = f"complaint_{update.message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = create_complaint_pdf(complaint_data, filename)
        complaint_data['pdf_path'] = pdf_path
        
        # Save to database
        complaint_id = save_complaint(complaint_data)
        
        summary = f"""✅ *Complaint Form Generated!*

👤 *Complainant:* {complaint_data['name']}
📋 *Type:* {complaint_type}
📍 *Location:* {incident_location}
🪪 *Aadhaar Verification:* Received and attached for police review

⚖️ *Applicable Laws:*
{applicable_laws}

📝 *Complaint ID:* #{complaint_id}

💡 *Next Steps:*
1️⃣ Visit the nearest police station
2️⃣ Carry this complaint form (PDF below)
3️⃣ Bring evidence & witnesses
4️⃣ Note FIR number after filing

📄 Your complaint PDF is ready below ⬇️"""
        
        await update.message.reply_text(summary, parse_mode='Markdown')
        
        with open(pdf_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=filename,
                caption="📄 Your complaint form\n\n🚨 For emergency: 100 | 112"
            )
        
    except Exception as e:
        logger.error(f"Error generating complaint PDF: {e}")
        await update.message.reply_text("❌ Error generating PDF. Please try again.")
    
    return ConversationHandler.END


# ============== RTI FILING ==============
async def rti_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start RTI filing"""
    await update.message.reply_text(
        "📄 *RTI Application Assistant*\n\n"
        "I'll help you file an RTI application under Right to Information Act, 2005.\n\n"
        "What is your *full name*?",
        parse_mode='Markdown'
    )
    context.user_data['rti'] = {
        'user_id': update.message.from_user.id,
        'aadhaar_photo_path': None,
        'otp_attempts': 0,
    }
    return RTI_NAME


async def rti_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rti']['name'] = update.message.text
    await update.message.reply_text("What is your *phone number*?", parse_mode='Markdown')
    return RTI_PHONE


async def rti_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text
    phone = normalize_phone_number(raw_phone)
    context.user_data['rti']['phone'] = phone

    if otp_service.send_otp(phone):
        context.user_data['rti']['otp_attempts'] = 0
        await update.message.reply_text(
            f"📲 OTP sent to `{phone}`. Please enter the 6-digit code.",
            parse_mode='Markdown'
        )
        return RTI_OTP

    await update.message.reply_text(
        "❌ I couldn't send an OTP. Please re-enter the phone number.",
        parse_mode='Markdown'
    )
    return RTI_PHONE


async def rti_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    rti_data = context.user_data['rti']
    phone = rti_data['phone']

    if code.lower() == "resend":
        if otp_service.send_otp(phone):
            await update.message.reply_text(
                f"🔁 New OTP sent to `{phone}`. Enter the code.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Couldn't resend OTP. Please try again later.",
                parse_mode='Markdown'
            )
        return RTI_OTP

    attempts = rti_data.get('otp_attempts', 0) + 1
    rti_data['otp_attempts'] = attempts

    if otp_service.verify_otp(phone, code):
        await update.message.reply_text(
            "✅ Phone verified!\n\nWhat is your *email address*? (Type 'skip' to skip)",
            parse_mode='Markdown'
        )
        return RTI_EMAIL

    if attempts >= 3:
        await update.message.reply_text(
            "❌ OTP verification failed repeatedly. Please /rti to restart.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "❌ Incorrect OTP. Try again or type *resend* for a new code.",
        parse_mode='Markdown'
    )
    return RTI_OTP


async def rti_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if email.lower() != 'skip':
        context.user_data['rti']['email'] = email
    
    await update.message.reply_text(
        "📎 Please upload a *clear image of your Aadhaar card* to verify this RTI request.\n\n"
        "• Tap the attachment icon to send the Aadhaar card photo\n"
        "• Details should be clearly visible\n"
        "• Type 'cancel' to stop the process",
        parse_mode='Markdown'
    )
    return RTI_AADHAAR


async def rti_aadhaar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rti_data = context.user_data['rti']
    message = update.message

    if message.text:
        if message.text.lower() == 'cancel':
            await update.message.reply_text("❌ RTI filing cancelled.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        await update.message.reply_text(
            "⚠️ Aadhaar verification image is required. Please upload a clear Aadhaar card photo.",
            parse_mode='Markdown'
        )
        return RTI_AADHAAR

    file = None
    filename_suffix = "jpg"

    if message.photo:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
    elif message.document:
        doc = message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await update.message.reply_text(
                "⚠️ Please upload the Aadhaar *as an image file* (jpg/png).",
                parse_mode='Markdown'
            )
            return RTI_AADHAAR
        file = await context.bot.get_file(doc.file_id)
        filename_suffix = (os.path.splitext(doc.file_name or "")[1].lstrip(".") or "jpg").lower()
    else:
        await update.message.reply_text(
            "⚠️ Please upload the Aadhaar *as an image file*.",
            parse_mode='Markdown'
        )
        return RTI_AADHAAR

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    aadhaar_dir = config.AADHAAR_RTI_DIR
    os.makedirs(aadhaar_dir, exist_ok=True)
    filename = f"aadhaar_rti_{update.message.from_user.id}_{timestamp}.{filename_suffix}"
    file_path = os.path.join(aadhaar_dir, filename)

    await file.download_to_drive(file_path)
    rti_data['aadhaar_photo_path'] = file_path

    await update.message.reply_text(
        "✅ Aadhaar card received.\n\nWhat is your *complete address*?",
        parse_mode='Markdown'
    )
    return RTI_ADDRESS


async def rti_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rti']['address'] = update.message.text
    await update.message.reply_text(
        "*Which government department/office* are you seeking information from?\n\n"
        "Example: Municipal Corporation, Revenue Department, Police Department, etc.",
        parse_mode='Markdown'
    )
    return RTI_DEPARTMENT


async def rti_department(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rti']['department'] = update.message.text
    await update.message.reply_text(
        "*What information are you seeking?*\n\n"
        "Be specific and clear about what information you want.",
        parse_mode='Markdown'
    )
    return RTI_INFO


async def rti_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rti']['information_sought'] = update.message.text
    await update.message.reply_text(
        "*Purpose of seeking information* (Optional)\n\n"
        "Type 'skip' to skip this field.",
        parse_mode='Markdown'
    )
    return RTI_PURPOSE


async def rti_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    purpose = update.message.text
    if purpose.lower() != 'skip':
        context.user_data['rti']['purpose'] = purpose
    
    await update.message.reply_text("⏳ Generating your RTI application...")
    
    rti_data = context.user_data['rti']
    
    try:
        filename = f"rti_{update.message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = create_rti_pdf(rti_data, filename)
        rti_data['pdf_path'] = pdf_path
        
        # Save to database
        rti_id = save_rti_request(rti_data)
        
        summary = f"""✅ *RTI Application Generated!*

👤 *Applicant:* {rti_data['name']}
🏛️ *Department:* {rti_data['department']}
🪪 *Aadhaar Verification:* Received and stored for official review

📝 *RTI ID:* #{rti_id}

💡 *Next Steps:*
1️⃣ Submit this application to the concerned Public Information Officer (PIO)
2️⃣ Pay the prescribed RTI fees (₹10 for central, varies for state)
3️⃣ Get acknowledgment with application number
4️⃣ Response should be provided within 30 days

📄 Your RTI application PDF is ready below ⬇️

⚖️ *RTI Act 2005 - Section 6(1)*
Information shall be provided within 30 days"""
        
        await update.message.reply_text(summary, parse_mode='Markdown')
        
        with open(pdf_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=filename,
                caption="📄 Your RTI Application\n\n💡 Submit to concerned PIO"
            )
        
    except Exception as e:
        logger.error(f"Error generating RTI PDF: {e}")
        await update.message.reply_text("❌ Error generating PDF. Please try again.")
    
    return ConversationHandler.END


# ============== TRAFFIC VIOLATION REPORTING ==============
async def traffic_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start traffic violation reporting"""
    await update.message.reply_text(
        "🚗 *Traffic Violation Reporting*\n\n"
        "Report illegal parking, traffic violations, etc.\n\n"
        "What is your *full name*?",
        parse_mode='Markdown'
    )
    context.user_data['traffic'] = {'user_id': update.message.from_user.id}
    return TRAFFIC_NAME


async def traffic_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['traffic']['reporter_name'] = update.message.text
    await update.message.reply_text("What is your *phone number*?", parse_mode='Markdown')
    return TRAFFIC_PHONE


async def traffic_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_phone = update.message.text
    phone = normalize_phone_number(raw_phone)
    context.user_data['traffic']['reporter_phone'] = phone

    if otp_service.send_otp(phone):
        context.user_data['traffic']['otp_attempts'] = 0
        await update.message.reply_text(
            f"📲 OTP sent to `{phone}`. Please enter the 6-digit code.",
            parse_mode='Markdown'
        )
        return TRAFFIC_OTP

    await update.message.reply_text(
        "❌ I couldn't send an OTP. Please re-enter the phone number.",
        parse_mode='Markdown'
    )
    return TRAFFIC_PHONE


async def traffic_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    traffic_data = context.user_data['traffic']
    phone = traffic_data['reporter_phone']

    if code.lower() == "resend":
        if otp_service.send_otp(phone):
            await update.message.reply_text(
                f"🔁 New OTP sent to `{phone}`. Enter the code.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Couldn't resend OTP. Please try again later.",
                parse_mode='Markdown'
            )
        return TRAFFIC_OTP

    attempts = traffic_data.get('otp_attempts', 0) + 1
    traffic_data['otp_attempts'] = attempts

    if otp_service.verify_otp(phone, code):
        await update.message.reply_text(
            "✅ Phone verified!\n\nWhat is the *vehicle number/plate*?",
            parse_mode='Markdown'
        )
        return TRAFFIC_VEHICLE

    if attempts >= 3:
        await update.message.reply_text(
            "❌ OTP verification failed several times. Please /traffic to restart.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "❌ Incorrect OTP. Try again or type *resend* for a new code.",
        parse_mode='Markdown'
    )
    return TRAFFIC_OTP


async def traffic_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['traffic']['vehicle_number'] = update.message.text
    
    keyboard = [
        ["Illegal Parking"],
        ["Wrong Side Driving"],
        ["Traffic Signal Violation"],
        ["Over Speeding"],
        ["Other Violation"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "*What type of violation?*\n\nSelect from the options below:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return TRAFFIC_TYPE


async def traffic_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['traffic']['violation_type'] = update.message.text
    
    location_button = KeyboardButton(text="📍 Share Location", request_location=True)
    keyboard = ReplyKeyboardMarkup([[location_button], ["Skip Location"]], one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "*Where did this occur?*\n\n"
        "Share your location or type the address:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    return TRAFFIC_LOCATION


async def traffic_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        location = update.message.location
        context.user_data['traffic']['latitude'] = location.latitude
        context.user_data['traffic']['longitude'] = location.longitude
        context.user_data['traffic']['location'] = f"Lat: {location.latitude}, Lng: {location.longitude}"
    else:
        context.user_data['traffic']['location'] = update.message.text
    
    await update.message.reply_text(
        "📸 *Upload a photo* of the violation (vehicle, number plate, etc.)\n\n"
        "Or type 'skip' if you don't have a photo.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return TRAFFIC_PHOTO


async def traffic_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        os.makedirs(config.TRAFFIC_DIR, exist_ok=True)
        filename = f"traffic_{update.message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        photo_path = os.path.join(config.TRAFFIC_DIR, filename)
        
        await file.download_to_drive(photo_path)
        context.user_data['traffic']['photo_path'] = photo_path
    
    await update.message.reply_text(
        "Any *additional details/description*?\n\n"
        "Or type 'no' to skip.",
        parse_mode='Markdown'
    )
    return TRAFFIC_DESC


async def traffic_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    if desc.lower() not in ['no', 'skip']:
        context.user_data['traffic']['description'] = desc
    
    await update.message.reply_text("⏳ Submitting your traffic violation report and generating PDF...")
    
    traffic_data = context.user_data['traffic']
    
    try:
        # Save to database
        violation_id = save_traffic_violation(traffic_data)
        
        # Generate PDF with photo
        from utils.pdf_generator import create_traffic_violation_pdf
        pdf_filename = f"traffic_violation_{update.message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = create_traffic_violation_pdf(traffic_data, f"storage/traffic_violations/{pdf_filename}")
        
        summary = f"""✅ *Traffic Violation Reported!*

🆔 *Report ID:* #{violation_id}
🚗 *Vehicle:* {traffic_data['vehicle_number']}
⚠️ *Violation:* {traffic_data['violation_type']}
📍 *Location:* {traffic_data['location']}

✅ Your report has been saved to the database and will be reviewed by traffic police.

💡 *What Happens Next:*
• Report is forwarded to traffic police
• Vehicle owner may receive challan/fine
• You may be contacted for additional details

📞 *Traffic Police Helpline:* 100

📄 *Your traffic violation report PDF is ready below* ⬇️"""
        
        await update.message.reply_text(summary, parse_mode='Markdown')
        
        # Send PDF with photo embedded
        with open(pdf_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=pdf_filename,
                caption=f"🚗 Traffic Violation Report #{violation_id}\n\n"
                        "📸 Photo evidence included in PDF\n"
                        "💡 This report has been submitted to traffic police"
            )
        
        # Don't delete PDF - keep it in storage for police to access
        
    except Exception as e:
        logger.error(f"Error saving traffic violation: {e}")
        await update.message.reply_text("❌ Error submitting report. Please try again.")
    
    return ConversationHandler.END


# ============== GENERAL MESSAGE HANDLERS ==============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general messages with AI"""
    user_message = update.message.text
    user_id = update.message.from_user.id
    
    await update.message.chat.send_action("typing")
    
    try:
        contextualized_message = f"""{user_message}

[Context: User is from Kakinada, Andhra Pradesh, India. Keep response under 2500 characters.]"""
        
        response_text = ai.send_message(user_id, contextualized_message)
        
        # Handle long responses
        if len(response_text) > 3800:
            chunks = [response_text[i:i+3800] for i in range(0, len(response_text), 3800)]
            for i, chunk in enumerate(chunks):
                try:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
                except Exception as markdown_error:
                    # Fallback to plain text if Markdown fails
                    logger.warning(f"Markdown parse failed for chunk {i}, sending as plain text: {markdown_error}")
                    await update.message.reply_text(chunk)
        else:
            try:
                await update.message.reply_text(response_text, parse_mode='Markdown')
            except Exception as markdown_error:
                # Fallback to plain text if Markdown fails
                logger.warning(f"Markdown parse failed, sending as plain text: {markdown_error}")
                await update.message.reply_text(response_text)
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "I apologize, I'm having trouble. Please try:\n"
            "/help - Show commands\n"
            "/complaint - File complaint\n"
            "/rti - File RTI"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages"""
    await update.message.reply_text("📸 Photo received! I can analyze images for legal documents.\n\n"
                                   "For traffic violations, please use /traffic command.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation"""
    await update.message.reply_text(
        "❌ Operation cancelled.\n\nUse /start to begin again.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ============== CALLBACK HELPERS ==============
async def schemes_callback(query, context):
    """Handle government schemes callback"""
    await query.message.reply_text(
        "🏛️ *Major Government Schemes (2025)*\n\n"
        "*Central Schemes:*\n"
        "• PM-KISAN - ₹6000/year for farmers\n"
        "• Ayushman Bharat - ₹5 lakh health cover\n"
        "• PMAY - Housing for all\n\n"
        "*AP State Schemes:*\n"
        "• Annadata Sukhibhava - ₹20,000/year for farmers\n"
        "• Talliki Vandanam - ₹15,000/year for students\n"
        "• Health Insurance - ₹25 lakh/family\n\n"
        "💡 Ask: 'Tell me about [scheme name]' for details!",
        parse_mode='Markdown'
    )


async def laws_callback(query, context):
    """Handle legal info callback"""
    await query.message.reply_text(
        "⚖️ *Legal Rights in India*\n\n"
        "*Fundamental Rights:*\n"
        "1️⃣ Right to Equality (Art. 14-18)\n"
        "2️⃣ Right to Freedom (Art. 19-22)\n"
        "3️⃣ Right Against Exploitation (Art. 23-24)\n"
        "4️⃣ Right to Freedom of Religion (Art. 25-28)\n"
        "5️⃣ Cultural & Educational Rights (Art. 29-30)\n"
        "6️⃣ Right to Constitutional Remedies (Art. 32)\n\n"
        "*Other Rights:*\n"
        "✅ Right to Free Legal Aid\n"
        "✅ Right to File FIR\n"
        "✅ Right to Information (RTI)\n"
        "✅ Right to Privacy\n\n"
        "💡 Ask me about specific laws!",
        parse_mode='Markdown'
    )


# ============== MAIN ==============
def main():
    """Start the bot"""
    application = Application.builder().token(config.PUBLIC_BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("police", police_stations))
    
    # Location handler
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    
    # Button handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Complaint conversation
    complaint_handler = ConversationHandler(
        entry_points=[CommandHandler("complaint", complaint_start)],
        states={
            COMPLAINT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_name)],
            COMPLAINT_FATHER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_father_name)],
            COMPLAINT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_age)],
            COMPLAINT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_phone)],
            COMPLAINT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_otp)],
            COMPLAINT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_email)],
            COMPLAINT_AADHAAR: [MessageHandler((filters.PHOTO | filters.Document.ALL | filters.TEXT) & ~filters.COMMAND, complaint_aadhaar)],
            COMPLAINT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_address)],
            COMPLAINT_INITIAL_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_initial_description)],
            COMPLAINT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_type)],
            COMPLAINT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_date)],
            COMPLAINT_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_location)],
            COMPLAINT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_description)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(complaint_handler)
    
    # RTI conversation
    rti_handler = ConversationHandler(
        entry_points=[CommandHandler("rti", rti_start)],
        states={
            RTI_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_name)],
            RTI_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_phone)],
            RTI_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_otp)],
            RTI_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_email)],
            RTI_AADHAAR: [MessageHandler((filters.PHOTO | filters.Document.ALL | filters.TEXT) & ~filters.COMMAND, rti_aadhaar)],
            RTI_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_address)],
            RTI_DEPARTMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_department)],
            RTI_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_info)],
            RTI_PURPOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rti_purpose)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(rti_handler)
    
    # Traffic violation conversation
    traffic_handler = ConversationHandler(
        entry_points=[CommandHandler("traffic", traffic_start)],
        states={
            TRAFFIC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_name)],
            TRAFFIC_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_phone)],
            TRAFFIC_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_otp)],
            TRAFFIC_VEHICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_vehicle)],
            TRAFFIC_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_type)],
            TRAFFIC_LOCATION: [MessageHandler((filters.TEXT | filters.LOCATION) & ~filters.COMMAND, traffic_location)],
            TRAFFIC_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, traffic_photo)],
            TRAFFIC_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, traffic_desc)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(traffic_handler)
    
    # General message handlers
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("[START] Public Bot (Kakinada Legal Assistant) is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

