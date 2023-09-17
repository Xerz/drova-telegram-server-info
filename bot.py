import os
import telegram
import telegram.ext
import requests
import json
import csv
import datetime
import time
import geoip2.database

# Dictionary to store X-Auth-Token for each chat ID
auth_tokens = {}
messages = []
ip_reader = geoip2.database.Reader("GeoLite2-City.mmdb")
ip_isp_reader = geoip2.database.Reader("GeoLite2-ASN.mmdb")
# Dictionary to store server IDs for each chat ID
server_ids = {}
# Set up the Telegram bot
bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

products_data = {}

# Load the products data from a JSON file
with open("products.json", "r") as f:
    products_data = json.load(f)


def send_sessions(update, context, edit_message=False, short_mode=False):
    chat_id = update.message.chat_id

    # Set up the endpoint URL and request parameters
    url = "https://services.drova.io/session-manager/sessions"

    # Retrieve user-specific params dictionary
    params = context.user_data.get("params", {})

    # Get the X-Auth-Token for this chat ID, or use the default value
    auth_token = auth_tokens.get(chat_id, "")

    response = requests.get(url, params=params, headers={"X-Auth-Token": auth_token})

    if response.status_code == 200:
        sessions = response.json()["sessions"]
        limit = int(params["limit"])
        message_long_text = " (excluding those shorter than 5 minutes)" if short_mode==True else ""
        message = f"Last {limit} sessions{message_long_text}:\n\n"

        created_on_past = ""

        for i, session in enumerate(reversed(sessions), start=1):
            product_id = session["product_id"]
            game_name = products_data.get(product_id, "Unknown game")
            if game_name == "Unknown game":
                products_data_update(update, context)
                game_name = products_data.get(product_id, "Unknown game")

            creator_ip = session.get("creator_ip", "N/A")
            creator_city = "X"
            try:
                creator_city = ip_reader.city(creator_ip).city.name
            except:
                pass
            creator_org = "X"
            try:
                creator_org = ip_isp_reader.asn(creator_ip).autonomous_system_organization
            except:
                pass

            client_id = session.get("client_id", "xxxxxx")[-6:]

            created_on = datetime.datetime.fromtimestamp(
                session["created_on"] / 1000.0
            ).strftime("%Y-%m-%d")
            start_time = datetime.datetime.fromtimestamp(
                session["created_on"] / 1000.0
            ).strftime("%H:%M:%S")
            finish_time = session["finished_on"]
            if finish_time:
                finish_time = datetime.datetime.fromtimestamp(
                    finish_time / 1000.0
                ).strftime("%H:%M:%S")
                duration = datetime.timedelta(
                        seconds=(session["finished_on"] - session["created_on"]) / 1000
                    )
            else:
                finish_time = "Now"
                duration = datetime.timedelta(
                        seconds=(datetime.datetime.now(datetime.datetime.UTC).timestamp() - session["created_on"]) / 1000
                    )
            duration_str = str(duration).split(".")[0]

            score_text = session.get("score_text", "N/A")

            if not created_on == created_on_past:
                message += f"<strong>{created_on}</strong>:\n"
                created_on_past = created_on

            if (not short_mode) or (short_mode and duration > datetime.timedelta(minutes=5)):
                message += f"{limit-i+1}. <strong>{game_name}</strong>\n"
                
                message += f"<code>{creator_ip}</code> <code>{client_id}</code>\n"
                
                message += f"{creator_city} {creator_org}\n{start_time}-{finish_time} ({duration_str})\n"

                message += f"Feedback: {score_text}\n" if not score_text == None else ""

                message += (
                    f"{session.get('billing_type', 'N/A')} {session['status'].lower()}\n\n"
                )

        current_time = datetime.datetime.now().strftime("%H:%M:%S")

        update_text = f"Update ({current_time})"

        update_callback_data = "update_sessions"
        if short_mode:
            update_callback_data += "_short"

        reply_markup = telegram.InlineKeyboardMarkup(
            [
                [
                    telegram.InlineKeyboardButton(
                        text=update_text, callback_data=update_callback_data
                    )
                ]
            ]
        )
        if edit_message:
            # Modify the original message with the updated session list
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=update.message.message_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode=telegram.ParseMode.HTML,
                )
            except telegram.TelegramError as e:
                pass

        else:
            # Send a new message with the updated session list
            bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode=telegram.ParseMode.HTML,
            )

    else:
        bot.send_message(chat_id=chat_id, text=f"Error: {response.status_code}")


# Define the callback function for the update sessions button
def update_sessions_callback(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    last_argument = query.data.split("_")[-1]
    short_mode = last_argument == "short"

    if "update_sessions" in query.data:
        # Modify the original message with the updated session list
        send_sessions(query, context, edit_message=True, short_mode=short_mode)
        query.answer()
    else:
        bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        query.answer()


# Set the X-Auth-Token for this chat ID
def set_auth_token(update, context):
    chat_id = update.message.chat_id
    token = context.args[0]
    print(context)

    # Store the X-Auth-Token for this chat ID
    auth_tokens[chat_id] = token

    params_defaults = {"server_id": "", "limit": "5"}

    context.user_data["params"] = params_defaults

    bot.send_message(chat_id=chat_id, text="X-Auth-Token has been set.")


# Set up the command handler for the '/station' command
def handle_station(update, context):
    chat_id = update.message.chat_id

    # Retrieve user-specific params dictionary
    params = context.user_data.get("params", {})

    # If the user provided an ID, update the params with the new station ID
    if len(context.args) > 0:
        station_id = context.args[0]
        params["server_id"] = station_id
        # Send a message to the user confirming the update
        bot.send_message(chat_id=chat_id, text=f"Station ID updated to {station_id}.")
    else:
        user_id = requests.get(
            "https://services.drova.io/accounting/myaccount",
            headers={"X-Auth-Token": auth_tokens.get(chat_id, "")},
        ).json()["uuid"]
        # Retrieve a list of available server IDs from the API
        response = requests.get(
            "https://services.drova.io/server-manager/servers",
            params={"user_id": user_id},
            headers={"X-Auth-Token": auth_tokens.get(chat_id, "")},
        )
        if response.status_code == 200:
            servers = response.json()
            # Create inline keyboard buttons for each available server ID
            keyboard = [
                [
                    telegram.InlineKeyboardButton(
                        text=s["name"], callback_data=f'set_server_id_{s["uuid"]}'
                    )
                    for s in servers
                ]
            ]
            # Send a message to the user with the list of server IDs as inline keyboard buttons
            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            bot.send_message(
                chat_id=chat_id, text="Select a station:", reply_markup=reply_markup
            )
        else:
            bot.send_message(chat_id=chat_id, text=f"Error: {response.status_code}")

    # Store the updated params dictionary back in the user's context
    context.user_data["params"] = params


def handle_limit(update, context):
    chat_id = update.message.chat_id
    # Retrieve user-specific params dictionary
    params = context.user_data.get("params", {})

    if len(context.args) > 0:
        limit = context.args[0]
        params["limit"] = limit
        # Send a message to the user confirming the update
        bot.send_message(chat_id=chat_id, text=f"Limit updated to {limit}.")

def handle_dump(update, context):
    chat_id = update.message.chat_id
    # Retrieve user-specific params dictionary
    params = context.user_data.get("params", {})

    # Set up the endpoint URL and request parameters
    url = "https://services.drova.io/session-manager/sessions"


    if len(context.args) == 0:
        # Get the X-Auth-Token for this chat ID, or use the default value
        auth_token = auth_tokens.get(chat_id, "")

        user_id = requests.get(
            "https://services.drova.io/accounting/myaccount",
            headers={"X-Auth-Token": auth_tokens.get(chat_id, "")},
        ).json()["uuid"]

        # Retrieve a list of available server IDs from the API
        servers_response = requests.get(
            "https://services.drova.io/server-manager/servers",
            params={"user_id": user_id},
            headers={"X-Auth-Token": auth_tokens.get(chat_id, "")},
        )

        if servers_response.status_code == 200:
            servers = servers_response.json()

            for s in servers:
                response = requests.get(url, params={"server_id": s["uuid"]}, headers={"X-Auth-Token": auth_token})
                if response.status_code == 200:
                    sessions = response.json()["sessions"]
                    for item in sessions:
                        product_id = item.get("product_id")
                        creator_ip = item.get("creator_ip")
                        creator_city = "X"
                        try:
                            creator_city = ip_reader.city(creator_ip).city.name
                        except:
                            pass
                        creator_org = "X"
                        try:
                            creator_org = ip_isp_reader.asn(creator_ip).autonomous_system_organization
                        except:
                            pass

                        game_name = products_data.get(product_id, "Unknown game")


                        created_on = datetime.datetime.fromtimestamp(
                            item["created_on"] / 1000.0
                        ).strftime("%Y-%m-%d")
                        start_time = datetime.datetime.fromtimestamp(
                            item["created_on"] / 1000.0
                        ).strftime("%H:%M:%S")
                        finish_time = item["finished_on"]
                        if finish_time:
                            finish_time = datetime.datetime.fromtimestamp(
                                finish_time / 1000.0
                            ).strftime("%H:%M:%S")
                            duration = datetime.timedelta(
                                    seconds=(item["finished_on"] - item["created_on"]) / 1000
                                )
                        else:
                            finish_time = "Now"
                            duration = datetime.timedelta(
                                    seconds=(datetime.datetime.now(datetime.datetime.UTC).timestamp() - item["created_on"]) / 1000
                                )
                        duration_str = str(duration).split(".")[0]

                        item["Game name"] = game_name
                        item["City"] = creator_city
                        item["ASN"] = creator_org
                        item["Duration"] = duration_str
                        item["Start time"] = start_time
                        item["Finish time"] = finish_time
                        item["Date"] = created_on

                    fieldnames = ['Game name','creator_ip','City','ASN','Date','Duration','Start time','Finish time', 'billing_type','status',  'abort_comment', 'client_id','id','uuid',  'server_id', 'merchant_id', 'product_id', 'created_on', 'finished_on', 'score', 'score_reason', 'score_text', 'parent', 'sched_hints']


                    csv_file = "sessions-" + s["name"] + ".csv"

                    # Write session data to CSV
                    with open(csv_file, 'w', newline='') as file:
                        writer = csv.DictWriter(file, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(sessions)
                    
                    bot.send_document(chat_id=chat_id, document=open(csv_file, "rb"))

        else:
            bot.send_message(chat_id=chat_id, text=f"Error: {response.status_code}")

    



def products_data_update(update, context):
    chat_id = update.message.chat_id
    # Retrieve user-specific params dictionary
    params = context.user_data.get("params", {})

    global products_data

    if len(context.args) == 0:
        products_data_len_old = len(products_data)

        response = requests.get(
            "https://services.drova.io/product-manager/product/listfull2",
            params={},
            headers={},
        )
        if response.status_code == 200:
            games = response.json()

            products_data_new = {}
            for game in games:
                products_data_new[game["productId"]] = game["title"]

            products_data = products_data_new

            products_data_len_new = len(products_data)

            with open("products.json", "w") as f:
                f.write(json.dumps(products_data))

            bot.send_message(
                chat_id=chat_id,
                text=f"Game database has been updated from {products_data_len_old} games to {products_data_len_new}",
            )
        else:
            bot.send_message(chat_id=chat_id, text=f"Error: {response.status_code}")


# Define the callback function for the set server ID buttons
def set_server_id_callback(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id
    server_id = query.data.split("_")[-1]

    # Store the server ID for this chat ID
    context.user_data["params"]["server_id"] = server_id

    bot.answer_callback_query(
        callback_query_id=query.id, text=f"Station ID updated to {server_id}."
    )


# Set up the command handler
def handle_command(update, context):
    command = update.message.text

    if "/sessions" in command:
        if len(context.args) > 0 and context.args[0] == "short":
            send_sessions(update, context, short_mode=True)
        else:
            send_sessions(update, context)
    elif command.startswith("/token"):
        set_auth_token(update, context)
    else:
        bot.send_message(
            chat_id=update.message.chat_id,
            text="Sorry, I don't understand that command.",
        )


# Set up the message handler
def handle_message(update, context):
    bot.send_message(
        chat_id=update.message.chat_id, text="Sorry, I don't understand that message."
    )


#  Set up the main function to handle updates
def main():
    updater = telegram.ext.Updater(
        token=os.environ["TELEGRAM_BOT_TOKEN"], use_context=True
    )
    dispatcher = updater.dispatcher

    # Add handlers for the '/sessions' command and regular text messages
    command_handler = telegram.ext.CommandHandler("sessions", handle_command)
    dispatcher.add_handler(command_handler)

    message_handler = telegram.ext.MessageHandler(
        telegram.ext.Filters.text & (~telegram.ext.Filters.command), handle_message
    )
    dispatcher.add_handler(message_handler)

    # Add a handler for the '/token' command
    token_handler = telegram.ext.CommandHandler("token", set_auth_token)
    dispatcher.add_handler(token_handler)

    # Set up the callback query handlers
    update_sessions_handler = telegram.ext.CallbackQueryHandler(
        update_sessions_callback, pattern="^update_sessions"
    )
    dispatcher.add_handler(update_sessions_handler)

    set_server_id_handler = telegram.ext.CallbackQueryHandler(
        set_server_id_callback, pattern="^set_server_id_"
    )
    dispatcher.add_handler(set_server_id_handler)

    # Set up the command handler for the '/station' command
    station_handler = telegram.ext.CommandHandler("station", handle_station)
    dispatcher.add_handler(station_handler)

    # Set up the command handler for the '/limit' command
    limit_handler = telegram.ext.CommandHandler("limit", handle_limit)
    dispatcher.add_handler(limit_handler)

    # Set up the command handler for the '/dumpall' command
    dump_handler = telegram.ext.CommandHandler("dumpall", handle_dump)
    dispatcher.add_handler(dump_handler)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
