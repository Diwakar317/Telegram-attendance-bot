from datetime import datetime, timedelta
import os
import pdfkit
import telebot
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from db_backend import db_session
from helpers import UTC_from_epoch, get_hashed, time_difference, to_IST, to_UTC
from models import Attendance, User
from settings import BOT_TOKEN, SELFIE_LOCATION_DELAY

bot = telebot.TeleBot(BOT_TOKEN)


# Create a new attendance record
def new_attendance(
    user_id: int,
    selfie: list = None,
    selfie_time: datetime = None,
    location: dict = None,
    location_time: datetime = None,
):
    if selfie_time or location_time:
        if selfie_time:
            attendance = Attendance(
                user_id=user_id, selfie=selfie, selfie_time=selfie_time
            )
        else:
            attendance = Attendance(
                user_id=user_id, location=location, location_time=location_time
            )

        db_session.add(attendance)
        db_session.commit()
    else:
        AssertionError("Either selfie or location required")


# When user starts a flow; welcome them
@bot.message_handler(commands=["start", "hello"])
@bot.message_handler(func=lambda msg: msg.text in ["start", "hello"])
def welcome_user(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        bot.reply_to(
            message,
            f"Hi, *{known_user.fullname}*; Welcome back",
            parse_mode="MarkdownV2",
        )
    else:
        bot.reply_to(
            message,
            "Please use command /login to interact further; example\n/login\nemployee ID\npassword \n\n"
            "or /help for other commands",
            parse_mode="MarkdownV2",
        )


# Show help options to users
@bot.message_handler(commands=["help"])
@bot.message_handler(func=lambda msg: msg.text in ["help"])
def help_msg(message):
    bot.reply_to(
        message,
        "/login \\- to login a user with employee ID and OTP followed by command\n"
        "/logout \\- to logout a user\n"
        "/create \\- HR can create a new user with their employee ID, name, role, OTP followed by command\n"
        "/download \\- user can download their monthly attendance by providing the month & year followed by command\n"
        "/rstpwd \\- HR can reset user password by providing employee ID & OTP followed by command\n"
        "/deactive \\- HR can deactivate an user by providing employee ID followed by command\n"
        "/reactive \\- HR can reactive an user by providing employee ID followed by command",
        parse_mode="MarkdownV2",
    )



#Logout Function - Keep user state active
@bot.message_handler(commands=["logout"])
@bot.message_handler(func=lambda msg: msg.text in ["logout"])
def logout_user(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)

    if known_user is None:
        bot.reply_to(message, "You are not currently logged in. Please log in first using /login.")
        return

    if not known_user.is_active:
        bot.reply_to(message, "Your account has been deactivated. Please contact HR for assistance.")
        return

    # Update user status
    known_user.is_logged_in = False  # Update to logged-out status
    known_user.last_chat_id = None    # Clear last chat ID
    db_session.add(known_user)
    db_session.commit()

    bot.reply_to(message, "You have been successfully logged out. You can log in again using the /login command.")

    # Optional logging for tracking
    print(f"User {known_user.employee_id} has logged out successfully.")

 #Login a user with employeeID & password
@bot.message_handler(commands=["login"])
def login_user(message):
    chat_id = message.chat.id
    try:
        _, emp_id, pwd = list(map(lambda x: x.strip(), message.text.split("\n")))
        print(f"Attempting login for Employee ID: {emp_id}")  # Debugging output
        
        # Validate credentials
        known_user = User.is_valid_credential(emp_id, pwd)
        if known_user is None:
            bot.reply_to(message, "Invalid credentials; login failed. Please check your Employee ID and password.")
            print(f"Login failed for Employee ID: {emp_id}")  # Debugging output
            return
        
        logged_in_user = User.get_by_emp_id(emp_id)
        if logged_in_user is None:
            bot.reply_to(message, "User not found; please ensure you are registered.")
            print(f"User not found for Employee ID: {emp_id}")  # Debugging output
            return
        
        # Set user session details
        logged_in_user.last_chat_id = str(chat_id)
        logged_in_user.is_logged_in = True  # Set the user state to logged in
        db_session.add(logged_in_user)
        db_session.commit()
        
        bot.reply_to(message, f"Hello *{known_user.fullname}*", parse_mode="MarkdownV2")
    except ValueError:
        bot.reply_to(message, "Please use command /login to interact further; example\n/login\nemployee ID\npassword", parse_mode="MarkdownV2")
    except Exception as e:
        bot.reply_to(message, f"An error occurred during login: {str(e)}")
        print(f"Exception during login: {str(e)}")  # Debugging output
# Create a new user with their employeeID, name, role & OTP
@bot.message_handler(commands=["create"])
@bot.message_handler(func=lambda msg: msg.text in ["create"])
def create_user(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        if known_user.role == "HR":
            try:
                _, emp_id, full_name, role, pwd = list(
                    map(lambda x: x.strip(), message.text.split("\n"))
                )
                if role.title() == "Employee":
                    role = "Employee"
                elif role.upper() == "HR":
                    role = "HR"
                else:
                    bot.reply_to(message, "Please provide Employee/HR as role")
                pwd = get_hashed(pwd)
                new_user = User(
                    employee_id=emp_id, fullname=full_name, role=role, temp_pwd=pwd
                )
                db_session.add(new_user)
                db_session.commit()
                bot.reply_to(message, "User has been added ", parse_mode="MarkdownV2")
            except ValueError:
                bot.reply_to(
                    message,
                    "Please use command /create to create user; "
                    "example\n/create\nemployee ID\nfull name\nrole\nOTP",
                    parse_mode="MarkdownV2",
                )
        else:
            bot.reply_to(message, "Sorry!! you can't use this command")
    else:
        bot.reply_to(message, "You are not yet logged in")


# Reset a password with employeeID & OTP
@bot.message_handler(commands=["rstpwd"])
@bot.message_handler(func=lambda msg: msg.text in ["rstpwd"])
def reset_password(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        if known_user.role == "HR":
            try:
                _, emp_id, pwd = list(
                    map(lambda x: x.strip(), message.text.split("\n"))
                )
                pwd = get_hashed(pwd)
                user = User.get_by_emp_id(emp_id)
                if user:
                    user.temp_pwd = pwd
                    user.is_pwd_expired = False
                    db_session.add(user)
                    db_session.commit()
                    bot.reply_to(
                        message, "New OTP has been updated", parse_mode="MarkdownV2"
                    )
                else:
                    bot.reply_to(
                        message,
                        "Employee doesn't exist or deactivated",
                        parse_mode="MarkdownV2",
                    )
            except ValueError:
                bot.reply_to(
                    message,
                    "Please use command /rstpwd to create user; "
                    "example\n/rstpwd\nemployee ID\nOTP",
                    parse_mode="MarkdownV2",
                )
        else:
            bot.reply_to(message, "Sorry!! you can't use this command")
    else:
        bot.reply_to(message, "You are not yet logged in")


# Deactivate user by their employee ID
@bot.message_handler(commands=["deactive"])
@bot.message_handler(func=lambda msg: msg.text in ["deactive"])
def deactivate_user(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        if known_user.role == "HR":
            try:
                _, emp_id = list(map(lambda x: x.strip(), message.text.split("\n")))
                print(f"[DEACTIVATE] HR {known_user.employee_id} requested deactivation for: {emp_id}")
                user = User.get_by_emp_id(emp_id)
                print(f"[DEACTIVATE] User found: {user}")
                if user:
                    if not user.is_active:
                        bot.reply_to(
                            message,
                            "User is already deactivated.",
                            parse_mode="MarkdownV2",
                        )
                        print(f"[DEACTIVATE] User {emp_id} already deactivated.")
                        return
                    user.is_active = False
                    db_session.add(user)
                    try:
                        db_session.commit()
                        bot.reply_to(
                            message, "User has been deactivated", parse_mode="MarkdownV2"
                        )
                        print(f"[DEACTIVATE] User {emp_id} deactivated successfully.")
                    except Exception as db_exc:
                        db_session.rollback()
                        bot.reply_to(
                            message,
                            f"Database error during deactivation: {db_exc}",
                            parse_mode="MarkdownV2",
                        )
                        print(f"[DEACTIVATE] DB error: {db_exc}")
                else:
                    bot.reply_to(
                        message,
                        "Employee doesn't exist or is already deactivated",
                        parse_mode="MarkdownV2",
                    )
                    print(f"[DEACTIVATE] No user found for {emp_id}.")
            except ValueError:
                bot.reply_to(
                    message,
                    "Please use command /deactive to create user; "
                    "example\n/deactive\nemployee ID",
                    parse_mode="MarkdownV2",
                )
                print("[DEACTIVATE] ValueError: Incorrect command format.")
        else:
            bot.reply_to(message, "Sorry!! you can't use this command")
            print(f"[DEACTIVATE] Non-HR user {known_user.employee_id} tried to deactivate.")
    else:
        bot.reply_to(message, "You are not yet logged in")
        print("[DEACTIVATE] Command issued by non-logged-in user.")


# Reactivate user with their employeeID
@bot.message_handler(commands=["reactive"])
@bot.message_handler(func=lambda msg: msg.text in ["reactive"])
def reactivate_user(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        if known_user.role == "HR":
            try:
                _, emp_id = list(map(lambda x: x.strip(), message.text.split("\n")))
                user = User.get_by_emp_id(emp_id, only_active=False)
                if user:
                    user.is_active = True
                    db_session.add(user)
                    db_session.commit()
                    bot.reply_to(
                        message, "User has been reactivated", parse_mode="MarkdownV2"
                    )
                else:
                    bot.reply_to(
                        message,
                        "Employee doesn't exist or deactivated",
                        parse_mode="MarkdownV2",
                    )
            except ValueError:
                bot.reply_to(
                    message,
                    "Please use command /deactive to create user; "
                    "example\n/deactive\nemployee ID",
                    parse_mode="MarkdownV2",
                )
        else:
            bot.reply_to(message, "Sorry!! you can't use this command")
    else:
        bot.reply_to(message, "You are not yet logged in")


# When user send a picture (selfie)
@bot.message_handler(content_types=["photo"])
def handle_attendance_selfie(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        curr_time = UTC_from_epoch(message.date)
        last_attendance = Attendance.get_last_attendance_record(
            known_user.id, curr_time
        )
        pictures = []
        for pic in message.photo:
            pictures.append(
                {
                    "file_id": pic.file_id,
                    "file_unique_id": pic.file_unique_id,
                    "width": pic.width,
                    "height": pic.height,
                    "file_size": pic.file_size,
                }
            )

        # Add facial recognition on message.photo[2] (best quality image) in future

        if last_attendance:
            # if a attendance is already present for today
            if last_attendance.selfie_time and last_attendance.location_time:
                # if the last record already have a selfie & location; create a new record
                try:
                    new_attendance(
                        user_id=known_user.id, selfie=pictures, selfie_time=curr_time
                    )
                    print(f"[ATTENDANCE] New selfie record created for user {known_user.id} at {curr_time}")
                    bot.reply_to(
                        message,
                        "Selfie has been added, Please share your location for attendance",
                    )
                except Exception as e:
                    db_session.rollback()
                    print(f"[ERROR] Failed to create selfie record: {e}")
                    bot.reply_to(message, "Error saving attendance. Please try again.")

            elif last_attendance.selfie_time:
                # if already selfie is present
                time_diff = (curr_time - last_attendance.selfie_time).total_seconds()
                if time_diff > SELFIE_LOCATION_DELAY:
                    # but the slack time is already passed
                    try:
                        new_attendance(
                            user_id=known_user.id, selfie=pictures, selfie_time=curr_time
                        )
                        print(f"[ATTENDANCE] New selfie record created for user {known_user.id} after delay at {curr_time}")
                        bot.reply_to(
                            message,
                            f"Oops.. You are unable to send location within <b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes",
                            parse_mode="HTML",
                        )
                        bot.send_message(
                            chat_id,
                            f"We have added your selfie, Please share your location within <b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes for attendance",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to create selfie record after delay: {e}")
                        bot.reply_to(message, "Error saving attendance. Please try again.")
                else:
                    # if still have some time left
                    time_left = SELFIE_LOCATION_DELAY - time_diff
                    bot.reply_to(
                        message,
                        "Selfie has been already received; "
                        f"Please send your location in <b>{time_left/60:.1f}</b> minutes for attendance",
                        parse_mode="HTML",
                    )

            elif last_attendance.location_time:
                # if location is already exists
                time_diff = (curr_time - last_attendance.location_time).total_seconds()
                if time_diff > SELFIE_LOCATION_DELAY:
                    # but slack time passed
                    try:
                        new_attendance(
                            user_id=known_user.id, selfie=pictures, selfie_time=curr_time
                        )
                        print(f"[ATTENDANCE] New selfie record created for user {known_user.id} after location delay at {curr_time}")
                        bot.reply_to(
                            message,
                            f"Oops.. You are unable to send selfie within <b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes",
                            parse_mode="HTML",
                        )
                        bot.send_message(
                            chat_id,
                            "We have added your selfie, Please share your location within "
                            f"<b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes for attendance",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to create selfie record after location delay: {e}")
                        bot.reply_to(message, "Error saving attendance. Please try again.")
                else:
                    # selfie sent within the slack time
                    last_attendance.selfie = pictures
                    last_attendance.selfie_time = curr_time
                    db_session.add(last_attendance)
                    try:
                        db_session.commit()
                        print(f"[ATTENDANCE] Updated selfie for user {known_user.id} at {curr_time}")
                        bot.reply_to(message, "Your attendance has been added 👍")
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to update selfie record: {e}")
                        bot.reply_to(message, "Error updating attendance. Please try again.")

        else:
            # if there are no record create a new record
            try:
                new_attendance(
                    user_id=known_user.id, selfie=pictures, selfie_time=curr_time
                )
                print(f"[ATTENDANCE] First selfie record created for user {known_user.id} at {curr_time}")
                bot.reply_to(
                    message,
                    "Selfie has been added, Please share your location for attendance",
                )
            except Exception as e:
                db_session.rollback()
                print(f"[ERROR] Failed to create first selfie record: {e}")
                bot.reply_to(message, "Error saving attendance. Please try again.")

    else:
        bot.reply_to(message, "You are not yet logged in")


# When user send location
@bot.message_handler(content_types=["location"])
def handle_attendance_location(message):
    chat_id = message.chat.id
    known_user = User.get_by_chat_id(chat_id)
    if known_user:
        curr_time = UTC_from_epoch(message.date)
        last_attendance = Attendance.get_last_attendance_record(
            known_user.id, curr_time
        )
        location = {
            "longitude": message.location.longitude,
            "latitude": message.location.latitude,
        }
        if last_attendance:
            # if a attendance is already present for today
            if last_attendance.selfie_time and last_attendance.location_time:
                # but both selfie and location has been added; create a new record
                try:
                    new_attendance(
                        user_id=known_user.id, location=location, location_time=curr_time
                    )
                    print(f"[ATTENDANCE] New location record created for user {known_user.id} at {curr_time}")
                    bot.reply_to(
                        message,
                        "Location has been added, Please share your selfie for attendance",
                    )
                except Exception as e:
                    db_session.rollback()
                    print(f"[ERROR] Failed to create location record: {e}")
                    bot.reply_to(message, "Error saving attendance. Please try again.")
            elif last_attendance.selfie_time:
                # and selfie is already present
                time_diff = (curr_time - last_attendance.selfie_time).total_seconds()
                if time_diff > SELFIE_LOCATION_DELAY:
                    # location is sent after slack time is over
                    try:
                        new_attendance(
                            user_id=known_user.id,
                            location=location,
                            location_time=curr_time,
                        )
                        print(f"[ATTENDANCE] New location record created for user {known_user.id} after delay at {curr_time}")
                        bot.reply_to(
                            message,
                            f"Oops.. You are unable to send location within <b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes",
                            parse_mode="HTML",
                        )
                        bot.send_message(
                            chat_id,
                            "We have added your location, Please share your selfie within "
                            f"<b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes for attendance",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to create location record after delay: {e}")
                        bot.reply_to(message, "Error saving attendance. Please try again.")
                else:
                    # location sent within the slack time
                    last_attendance.location = location
                    last_attendance.location_time = curr_time
                    db_session.add(last_attendance)
                    try:
                        db_session.commit()
                        print(f"[ATTENDANCE] Updated location for user {known_user.id} at {curr_time}")
                        bot.reply_to(message, "Your attendance has been added 👍")
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to update location record: {e}")
                        bot.reply_to(message, "Error updating attendance. Please try again.")
            elif last_attendance.location_time:
                # and location is already present
                time_diff = (curr_time - last_attendance.location_time).total_seconds()
                if time_diff > SELFIE_LOCATION_DELAY:
                    # if location is sent after slack time
                    try:
                        new_attendance(
                            user_id=known_user.id,
                            location=location,
                            location_time=curr_time,
                        )
                        print(f"[ATTENDANCE] New location record created for user {known_user.id} after selfie delay at {curr_time}")
                        bot.reply_to(
                            message,
                            f"Oops.. You are unable to send selfie within <b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes",
                            parse_mode="HTML",
                        )
                        bot.send_message(
                            chat_id,
                            "We have added your location, Please share your selfie within "
                            f"<b>{SELFIE_LOCATION_DELAY / 60:.1f}</b> minutes for attendance",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        db_session.rollback()
                        print(f"[ERROR] Failed to create location record after selfie delay: {e}")
                        bot.reply_to(message, "Error saving attendance. Please try again.")
                else:
                    # if still have some time left
                    time_left = SELFIE_LOCATION_DELAY - time_diff
                    bot.reply_to(
                        message,
                        "Location has been already received; "
                        f"Please send your selfie in <b>{time_left / 60:.1f}</b> minutes for attendance",
                        parse_mode="HTML",
                    )
        else:
            # if there are no record create a new record
            try:
                new_attendance(
                    user_id=known_user.id, location=location, location_time=curr_time
                )
                print(f"[ATTENDANCE] First location record created for user {known_user.id} at {curr_time}")
                bot.reply_to(
                    message,
                    "Location has been added, Please share your selfie for attendance",
                )
            except Exception as e:
                db_session.rollback()
                print(f"[ERROR] Failed to create first location record: {e}")
                bot.reply_to(message, "Error saving attendance. Please try again.")
    else:
        bot.reply_to(message, "You are not yet logged in")


# Download attendance report
@bot.message_handler(func=lambda msg: msg.text.strip().lower() == "download")
def download_report(message):
    bot.reply_to(
        message,
        "This feature is under development; Please contact your administrator for assistance",
    )


# When user send any message except the commands, picture or location (Fallback State)
@bot.message_handler(func=lambda msg: True)
def echo_all(message):
    bot.reply_to(
        message,
        "Sorry I can't help you in this; Please checkout /help or contact your administrator",
    )


print("[BOT] Telegram Attendance Bot is starting...")
try:
    bot.infinity_polling()
except Exception as e:
    print(f"[BOT] Telegram Attendance Bot stopped due to error: {e}")
else:
    print("[BOT] Telegram Attendance Bot stopped.")