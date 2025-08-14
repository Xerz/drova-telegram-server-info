import os
import logging
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import api
import services
import json
import datetime
 

from storage import (
    persistentData,
    setUserID,
    setAuthToken,
    getAuthTokensByChatID,
    setSelectedStationID,
    setLimit,
)
from geo_utils import (
    tryLoadGeodb,
)
 

bot = None  # context.bot will be used in PTB v21

products_data = {}
# Load the products data from a JSON file
try:
    with open("products.json", "r") as f:
        products_data = json.load(f)
except:
    pass

async def send_sessions(update, context: ContextTypes.DEFAULT_TYPE, edit_message=False, short_mode=False):
    chat_id = update.effective_chat.id if hasattr(update, "effective_chat") and update.effective_chat else update.callback_query.message.chat.id
    global products_data

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    server_id=persistentData['selectedStations'].get(str(chat_id), None)

    limit =persistentData['limits'].get(str(chat_id), 5)
    params={ "limit":limit}
    currentStationName=""
    if not server_id is None:
        params['server_id']=server_id
        currentStations=persistentData['stationNames'].get(str(chat_id),None)
        if not currentStations is None:
            currentStationName=persistentData['stationNames'][str(chat_id)].get(server_id,None)

    message, currentStationName, unknown_missing, status = services.build_sessions_message(
        authToken, chat_id, server_id, limit, short_mode, products_data
    )
    if status != 200:
        await context.bot.send_message(chat_id=chat_id, text=message)
        return

    if unknown_missing:
        products_data, old_count, new_count = services.update_products_data()
        message, currentStationName, _, status = services.build_sessions_message(
            authToken, chat_id, server_id, limit, short_mode, products_data
        )

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    update_text = f"Update {currentStationName} ({current_time})"
    update_callback_data = "update_sessions"
    if short_mode:
        update_callback_data += "_short"

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=update_text, callback_data=update_callback_data)]]
    )
    if edit_message:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )


# Define the callback function for the update sessions button
async def update_sessions_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    message_id = query.message.message_id
    last_argument = query.data.split("_")[-1]
    short_mode = last_argument == "short"

    if "update_sessions" in query.data:
        # Modify the original message with the updated session list
        await send_sessions(update, context, edit_message=True, short_mode=short_mode)
        await query.answer()
    else:
        await context.bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        await query.answer()


# Set the X-Auth-Token for this chat ID
async def set_auth_token(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if len(context.args)==0:
        await context.bot.send_message(chat_id=chat_id, text=f"add token to command like /token 123-456-789")
        return
    
    token = context.args[0]

    accountInfo, status = api.get_account_info(token)
    
    if status == 200 and accountInfo is not None:
        if('uuid' in accountInfo):
            # Store the X-Auth-Token for this chat ID
            setAuthToken(chat_id,token)
            setUserID(chat_id,accountInfo['uuid'])
            await context.bot.send_message(chat_id=chat_id, text=f"X-Auth-Token has been set.\r\nПривет {accountInfo['name']}")
            # Refresh products cache silently and update station names
            global products_data
            products_data, _, _ = services.update_products_data()
            services.get_servers_and_store_names(token, accountInfo['uuid'], chat_id)
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"Token error, not set.")
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"Token error, not set.")
    
async def removeAuthToken(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    result=setAuthToken(chat_id,"-")
    if result:
        await context.bot.send_message(chat_id=chat_id, text=f"Token removed.")


def updateStationNames(chat_id):
    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        return
    user_id = persistentData['userIDs'].get(str(chat_id), None)
    services.get_servers_and_store_names(authToken, user_id, chat_id)


async def handle_start(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    helpText="""Не добавляйте токены в непроверенных ботов - владелец бота получит информацию из вашего ЛК!
Команды:
/token 123-456-789 - установить токен из qr кода личного кабинета мерчанта
/removeToken - удалить токен пользователя из бота
/current - Краткий список последних сессий по всем станциям
/station [id станции] - выбор станции из списка или ручным вводом её id
/limit N - смена ограничения на вывод сессий
/sessions [short] - просмотр сессий со всех или с выбранной станции
/dumpall - экспорт сессий по серверам
/dumpOnefile - экспорт сессий одним файлом
"""

    await context.bot.send_message(chat_id=chat_id, text=helpText)


# Define the callback function for the update button
async def update_disabled_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id

    if "update_disabled" in query.data:
        # Modify the original message 
        await handle_disabled(query, context, edit_message=True)
        await query.answer()
    else:
        await context.bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        await query.answer()

# Define the callback function for the update button
async def update_stationsinfo_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id

    if "update_stationsinfo" in query.data:
        # Modify the original message 
        await handle_stationsinfo(query, context, edit_message=True)
        await query.answer()
    else:
        await context.bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        await query.answer()

def getProductState(product,okState=""):
    return services.get_product_state(product, okState)

async def handle_stationsinfo(update,context: ContextTypes.DEFAULT_TYPE, edit_message=False):
    chat_id = update.effective_chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    text, status = services.build_stations_info_message(authToken, user_id, chat_id)
    if status != 200:
        await context.bot.send_message(chat_id=chat_id, text=f"Error")
        return

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    update_text = f"Update ({current_time})"
    update_callback_data = "update_stationsinfo"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=update_text, callback_data=update_callback_data)]]
    )
    if edit_message:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def handle_disabled(update,context: ContextTypes.DEFAULT_TYPE, edit_message=False):
    chat_id = update.effective_chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    text, status = services.build_disabled_products_message(authToken, user_id)
    if status != 200:
        await context.bot.send_message(chat_id=chat_id, text=f"Error")
        return

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    update_text = f"Update ({current_time})"
    update_callback_data = "update_disabled"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=update_text, callback_data=update_callback_data)]]
    )
    if edit_message:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# Define the callback function for the update button
async def update_current_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id

    if "update_current" in query.data:
        await handle_current(update, context, edit_message=True)
        await query.answer()
    else:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, I don't understand that command.")
        await query.answer()


def formatStationName(station,session):
    return services.format_station_name(station, session)


# Set up the command handler for the '/current' command
async def handle_current(update, context: ContextTypes.DEFAULT_TYPE, edit_message=False):
    chat_id = update.effective_chat.id if hasattr(update, "effective_chat") and update.effective_chat else update.callback_query.message.chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    text, status = services.build_current_message(authToken, user_id, chat_id, products_data)
    if status != 200:
        await context.bot.send_message(chat_id=chat_id, text=f"Error")
        return

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    update_text = f"Update ({current_time})"
    update_callback_data = "update_current"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=update_text, callback_data=update_callback_data)]]
    )
    if edit_message:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=update.effective_message.message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)




# Set up the command handler for the '/station' command
async def handle_station(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    # If the user provided an ID, update the params with the new station ID
    if len(context.args) > 0:
        station_id = context.args[0]
        setSelectedStationID(chat_id,station_id)
        # Send a message to the user confirming the update
        await context.bot.send_message(chat_id=chat_id, text=f"Station ID updated to {station_id}.")
    else:
        user_id = persistentData['userIDs'].get(str(chat_id), None)

        # Retrieve a list of available server IDs from the API
        servers, status = services.get_servers_and_store_names(authToken, user_id, chat_id)

        if status == 200 and servers is not None:

            servers.append({'uuid':"-","name":"all"})

            # Create inline keyboard buttons for each available server ID
            keyboard = [[InlineKeyboardButton(text=s["name"], callback_data=f'set_server_id_{s["uuid"]}') for s in servers]]
            # Send a message to the user with the list of server IDs as inline keyboard buttons
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id, text="Select a station:", reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: {status}")

async def handle_limit(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    if len(context.args) > 0:
        limit = context.args[0]
        setLimit(chat_id,limit)
        # Send a message to the user confirming the update
        await context.bot.send_message(chat_id=chat_id, text=f"Limit updated to {limit}.")
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"add limit number to command")

def filterSessionsByProductAndDays(stationSessions,productID,daysLimit=30):
    return services.filter_sessions_by_product_and_days(stationSessions, productID, daysLimit)

def calcSessionsDuration(sessions):
    return services.calc_sessions_duration(sessions)

async def handle_dumpstantionsproducts(update,context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    withTime=False
    daysLimit=0
    cmd = (update['message']['text']).lower()
    if cmd == "/dumpstationsproductswithtime":
        withTime=True
    if cmd == "/dumpstationsproductsmonth":
        withTime=True
        daysLimit=30

    attachment, status = services.export_stations_products(authToken, user_id, chat_id, withTime, daysLimit)
    if status != 200:
        await context.bot.send_message(chat_id=chat_id, text="Error")
        return
    if not attachment:
        await context.bot.send_message(chat_id=chat_id, text="No data")
        return
    filename, buf = attachment
    await context.bot.send_document(chat_id=chat_id, document=buf)



async def handle_dump(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    authToken=getAuthTokensByChatID(chat_id)
    if authToken is None:
        await context.bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    dumpOnefile = False
    if (update['message']['text']).lower() == "/dumponefile":
        dumpOnefile = True

    if len(context.args) == 0:
        user_id = persistentData['userIDs'].get(str(chat_id), None)
        attachments, status = services.export_sessions(authToken, user_id, dumpOnefile, products_data)
        if status != 200:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: {status}")
            return
        if len(attachments) == 0:
            await context.bot.send_message(chat_id=chat_id, text="No data")
            return
        for filename, buf in attachments:
            await context.bot.send_document(chat_id=chat_id, document=buf)

    



async def products_data_update(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    global products_data
    products_data, old_len, new_len = services.update_products_data()
    await context.bot.send_message(chat_id=chat_id, text=f"Game database has been updated from {old_len} games to {new_len}")


# Define the callback function for the set server ID buttons
async def set_server_id_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    server_id = query.data.split("_")[-1]

    # Store the server ID for this chat ID
    setSelectedStationID(chat_id,server_id)

    if server_id=="-":
        message=f"Selected all stations."
    else:
        message=f"Station ID updated to {server_id}."

    await query.answer(text=message)


# Set up the command handler
async def handle_command(update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text

    if "/sessions" in command:
        if len(context.args) > 0 and context.args[0] == "short":
            await send_sessions(update, context, short_mode=True)
        else:
            await send_sessions(update, context)
    elif command.startswith("/token"):
        await set_auth_token(update, context)
    else:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, I don't understand that command.")


# Set up the message handler
async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I don't understand that message.")


#  Set up the main function to handle updates
def main():
    # Configure logging level from LOG_LEVEL env var
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger(__name__).info(f"Starting bot with LOG_LEVEL={level_str}")
    tryLoadGeodb()

    application = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]) .build()

    # Add handlers for the '/sessions' command and regular text messages
    command_handler = CommandHandler("sessions", handle_command)
    application.add_handler(command_handler)

    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    # Add a handler for the '/token' command
    token_handler = CommandHandler("token", set_auth_token)
    application.add_handler(token_handler)

    # Add a handler for the '/removeToken' command
    remove_token_handler = CommandHandler("removeToken", removeAuthToken)
    application.add_handler(remove_token_handler)

    # Set up the callback query handlers
    update_sessions_handler = CallbackQueryHandler(update_sessions_callback, pattern="^update_sessions")
    application.add_handler(update_sessions_handler)

    set_server_id_handler = CallbackQueryHandler(set_server_id_callback, pattern="^set_server_id_")
    application.add_handler(set_server_id_handler)

    # Set up the callback query handlers
    update_current_handler = CallbackQueryHandler(update_current_callback, pattern="^update_current")
    application.add_handler(update_current_handler)

    # Set up the command handler for the '/current' command
    current_handler = CommandHandler("current", handle_current)
    application.add_handler(current_handler)

    # Set up the callback query handlers
    update_disabled_handler = CallbackQueryHandler(update_disabled_callback, pattern="^update_disabled")
    application.add_handler(update_disabled_handler)

    # Set up the command handler for the '/disabled' command
    disabled_handler = CommandHandler("disabled", handle_disabled)
    application.add_handler(disabled_handler)

    # Set up the callback query handlers
    update_stationsinfo_handler = CallbackQueryHandler(update_stationsinfo_callback, pattern="^update_stationsinfo")
    application.add_handler(update_stationsinfo_handler)

    # Set up the command handler for the '/stationsinfo' command
    stationsinfo_handler = CommandHandler("stationsInfo", handle_stationsinfo)
    application.add_handler(stationsinfo_handler)

    # Set up the command handler for the '/start' command
    start_handler = CommandHandler("start", handle_start)
    application.add_handler(start_handler)

    # Set up the command handler for the '/station' command
    station_handler = CommandHandler("station", handle_station)
    application.add_handler(station_handler)

    # Set up the command handler for the '/limit' command
    limit_handler = CommandHandler("limit", handle_limit)
    application.add_handler(limit_handler)

    # Set up the command handler for the '/dumpall' command
    dump_handler = CommandHandler("dumpall", handle_dump)
    application.add_handler(dump_handler)

    dump_handler2 = CommandHandler("dumpOnefile", handle_dump)
    application.add_handler(dump_handler2)

    dump_stantionsproducts = CommandHandler("dumpStationsProducts", handle_dumpstantionsproducts)
    application.add_handler(dump_stantionsproducts)

    dump_stantionsproducts2 = CommandHandler("dumpStationsProductsWithTime", handle_dumpstantionsproducts)
    application.add_handler(dump_stantionsproducts2)
    dump_stantionsproducts3 = CommandHandler("dumpStationsProductsMonth", handle_dumpstantionsproducts)
    application.add_handler(dump_stantionsproducts3)

    application.run_polling()


if __name__ == "__main__":
    main()
