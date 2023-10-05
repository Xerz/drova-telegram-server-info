import os
import io
import telegram
import telegram.ext
import requests
import json
import csv
import datetime
import math
import time
import ipaddress
import geoip2.database
from openpyxl import Workbook
from openpyxl.styles import PatternFill,Alignment

ip_reader = geoip2.database.Reader("GeoLite2-City.mmdb")
ip_isp_reader = geoip2.database.Reader("GeoLite2-ASN.mmdb")

bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])

products_data = {}
persistentData= {
    "authTokens": {},
    "userIDs":{},
    "limits":{},
    "selectedStations": {},
    "stationNames":{},
}

# Load the products data from a JSON file
try:
    with open("products.json", "r") as f:
        products_data = json.load(f)
except:
    pass

# Load the auth tokens from a JSON file
try:
    with open("persistentData.json", 'r') as f:
        persistentData = json.load(f)
except:
    pass


def isRfc1918Ip(ip):
    try:
        ip = ipaddress.ip_address(ip)
        rfc1918Ranges = [
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12'),
            ipaddress.ip_network('192.168.0.0/16'),
        ]
        for rfcRange in rfc1918Ranges:
            if ip in rfcRange:
                return True
        return False
    except ValueError:
        # Invalid IP address format
        return False

def storePersistentData():
    try:
        with open("persistentData.json", 'w') as f:
            json.dump(persistentData, f, indent=4)
    except:
        pass

def setUserID(chatID,userID):
    if 'userIDs'not in persistentData:
       persistentData['userIDs'] = {}
    persistentData['userIDs'][str(chatID)]=userID
    storePersistentData()

def setAuthToken(chatID,authToken):
    if 'authTokens'not in persistentData:
       persistentData['authTokens'] = {}
    
    if authToken=="-" and str(chatID) in persistentData['authTokens']:
        del persistentData['authTokens'][str(chatID)]
        storePersistentData()
        return True
    elif authToken!="-":
        persistentData['authTokens'][str(chatID)]=authToken
        storePersistentData()

def setSelectedStationID(chatID,stationID):
    if 'selectedStations'not in persistentData:
       persistentData['selectedStations'] = {}
    if stationID=="-" and str(chatID) in persistentData['selectedStations']:
        del persistentData['selectedStations'][str(chatID)]
    elif stationID!="-":
        persistentData['selectedStations'][str(chatID)]=stationID
    storePersistentData()

def setLimit(chatID,limit):
    if 'limits'not in persistentData:
       persistentData['limits'] = {}
    persistentData['limits'][str(chatID)]=int(limit)
    storePersistentData()

def storeStationNames(chatID,stations):
    if 'stationNames'not in persistentData:
       persistentData['stationNames'] = {}
    persistentData['stationNames'][str(chatID)]=stations
    storePersistentData()    

def getStationNamesWithID(chatID):
    stations={}
    if 'stationNames'not in persistentData and  str(chatID) in persistentData['stationNames']:
        for id,name in persistentData['stationNames'][str(chatID)]:
            stations[name]=id
    return stations


def formatDuration(elapsed_time,shortFormat=True):
    if elapsed_time < 3600 and  shortFormat:
        minutes, seconds = divmod(elapsed_time, 60)
        return "{:.0f}m:{:.0f}s ".format(minutes,seconds)
    elif elapsed_time < 86400 and  shortFormat:
        hours, remainder = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:.0f}h {:.0f}m".format(hours, minutes)
    else:
        days, remainder = divmod(elapsed_time, 86400)
        fullhours= elapsed_time/3600
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if   shortFormat:
            return "{:.0f}d {:.0f}h {:.0f}m".format(days, hours, minutes)
        else:
            return "{:02.0f}:{:02.0f}:{:02.0f}".format(fullhours, minutes,seconds)
            #return "{:.0f} {:02.0f}:{:02.0f}:{:02.0f}".format(days, hours, minutes,seconds)

def getSessionDuration(session):
    if session['finished_on'] is None:
        duration=(datetime.datetime.now().timestamp()-session['created_on']/1000)
    else:
        duration=(session['finished_on']-session['created_on'])/1000
    return duration

def getCityByIP(creator_ip,defValue=""):
    creator_city=defValue
    try:
        creator_city = ip_reader.city(creator_ip).city.name
    except:
        pass
    if creator_city is None:
        creator_city = defValue
    return creator_city

def getOrgByIP(creator_ip,defValue=""):
    creator_org = defValue
    try:
        creator_org = ip_isp_reader.asn(creator_ip).autonomous_system_organization
    except:
        pass
    if creator_org is None:
        creator_org = defValue
    return creator_org

def haversineDistance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points on the Earth's surface
    specified in decimal degrees of latitude and longitude.

    :param lat1: Latitude of the first point in degrees.
    :param lon1: Longitude of the first point in degrees.
    :param lat2: Latitude of the second point in degrees.
    :param lon2: Longitude of the second point in degrees.
    :return: The distance in kilometers.
    """

    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return -1

    # Convert latitude and longitude from degrees to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    # Radius of the Earth in kilometers
    earth_radius = 6371.0

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # Calculate the distance
    distance = earth_radius * c

    return distance

def calcRangeByIp(station,clientIp):
    cityInfo=None
    try:
        cityInfo = ip_reader.city(clientIp).location
    except:
        pass

    if cityInfo!=None:
        clientLatitude=cityInfo.latitude
        clientLongitude=cityInfo.longitude
        return round( haversineDistance(station['latitude'],station['longitude'],clientLatitude,clientLongitude),1)

    return -1
    
def send_sessions(update, context, edit_message=False, short_mode=False):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    server_id=persistentData['selectedStations'].get(str(chat_id), None)

    # Set up the endpoint URL and request parameters
    url = "https://services.drova.io/session-manager/sessions"

    limit =persistentData['limits'].get(str(chat_id), 5)
    params={ "limit":limit}
    currentStationName=""
    if not server_id is None:
        params['server_id']=server_id
        currentStations=persistentData['stationNames'].get(str(chat_id),None)
        if not currentStations is None:
            currentStationName=persistentData['stationNames'][str(chat_id)].get(server_id,None)

    response = requests.get(url, params=params, headers={"X-Auth-Token": authToken})

    if response.status_code == 200:
        sessions = response.json()["sessions"]
        message_long_text = " (excluding those shorter than 5 minutes)" if short_mode==True else ""
        message = f"Last {limit} sessions{message_long_text}:\n\n"

        created_on_past = ""

        for i, session in enumerate(reversed(sessions), start=1):
            product_id = session["product_id"]
            game_name = products_data.get(product_id, "Unknown game")
            if game_name == "Unknown game":
                products_data_update(update, context)
                game_name = products_data.get(product_id, "Unknown game")

            serverName=""
            if server_id is None and str(chat_id) in persistentData['stationNames']:
                serverName=persistentData['stationNames'][str(chat_id)].get(session['server_id'],"")
                if serverName!="":
                    serverName+="\r\n"


            creator_ip = session.get("creator_ip", "N/A")
            creator_city= getCityByIP(creator_ip,"X")
            creator_org= getOrgByIP(creator_ip,"X")

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
                duration = datetime.timedelta(seconds=(session["finished_on"] - session["created_on"]) / 1000)
            else:
                finish_time = "Now"
                duration = datetime.timedelta(seconds=datetime.datetime.utcnow().timestamp() - session["created_on"] / 1000)
            #duration_str = str(duration).split(".")[0]
            duration_str =formatDuration( getSessionDuration(session))

            score_text = session.get("score_text", "N/A")

            if not created_on == created_on_past:
                message += f"<strong>{created_on}</strong>:\n"
                created_on_past = created_on

            if (not short_mode) or (short_mode and duration > datetime.timedelta(minutes=5)):
                message += f"{limit-i+1}. <strong>{game_name}</strong>\n"
                message += serverName
                message += f"<code>{creator_ip}</code> <code>{client_id}</code>\n"
                
                message += f"{creator_city} {creator_org}\n{start_time}-{finish_time} ({duration_str})\n"

                message += f"Feedback: {score_text}\n" if not score_text == None else ""

                message += (
                    f"{session.get('billing_type', 'N/A')} {session['status'].lower()}\n\n"
                )

        current_time = datetime.datetime.now().strftime("%H:%M:%S")

        update_text = f"Update {currentStationName} ({current_time})"

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
    
    if len(context.args)==0:
        bot.send_message(chat_id=chat_id, text=f"add token to command like /token 123-456-789")
        return
    
    token = context.args[0]

    accountResp = requests.get(
        "https://services.drova.io/accounting/myaccount",
        headers={"X-Auth-Token": token},
    )
    
    if accountResp.status_code == 200:
        accountInfo = accountResp.json()
        if('uuid' in accountInfo):
            # Store the X-Auth-Token for this chat ID
            setAuthToken(chat_id,token)
            setUserID(chat_id,accountInfo['uuid'])
            bot.send_message(chat_id=chat_id, text=f"X-Auth-Token has been set.\r\nПривет {accountInfo['name']}")
            products_data_update(update, context)
            updateStationNames(chat_id)
        else:
            bot.send_message(chat_id=chat_id, text=f"Token error, not set.")
    else:
        bot.send_message(chat_id=chat_id, text=f"Token error, not set.")
    
def removeAuthToken(update, context):
    chat_id = update.message.chat_id
    result=setAuthToken(chat_id,"-")
    if result:
        bot.send_message(chat_id=chat_id, text=f"Token removed.")


def updateStationNames(chat_id):
    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    user_id = persistentData['userIDs'].get(str(chat_id), None)
    getServers(authToken,user_id,chat_id)


def handle_start(update, context):
    chat_id = update.message.chat_id

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

    bot.send_message(chat_id=chat_id, text=helpText)


def getSessions(authToken,server_id):
    response = requests.get("https://services.drova.io/session-manager/sessions", params={"server_id": server_id}, headers={"X-Auth-Token": authToken})
    if response.status_code == 200:
        return response.json()["sessions"]   
    return None

def getServers(authToken,user_id,chat_id):
    # Retrieve a list of available server IDs from the API
    response = requests.get(
        "https://services.drova.io/server-manager/servers",
        params={"user_id": user_id},
        headers={"X-Auth-Token": authToken},
    )
    if response.status_code == 200:
        servers=response.json()
        if not servers is None:
            if len(servers)>0:
                stationNames={}
                for s in servers:
                    stationNames[s['uuid']]=s['name']
                storeStationNames(chat_id,stationNames)
        return servers

def getServerProducts(authToken,user_id,server_id):
    response = requests.get(
        "https://services.drova.io/server-manager/serverproduct/list4edit2/"+server_id,
        params={"user_id": user_id},
        headers={"X-Auth-Token": authToken},
    )
    if response.status_code == 200:
        return response.json()


# Define the callback function for the update button
def update_disabled_callback(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id

    if "update_disabled" in query.data:
        # Modify the original message 
        handle_disabled(query, context, edit_message=True)
        query.answer()
    else:
        bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        query.answer()

# Define the callback function for the update button
def update_stationsinfo_callback(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id

    if "update_stationsinfo" in query.data:
        # Modify the original message 
        handle_stationsinfo(query, context, edit_message=True)
        query.answer()
    else:
        bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        query.answer()

def getProductState(product,okState=""):
    info=""
    if not product['enabled']:
        info+=" Not enabled"
    if not product['published']:
        info+=" Not published"
    if not product['available']:
        info+=" Not available"

    if info=="":
        return (False,okState)
    
    return (True,info)

def handle_stationsinfo(update,context, edit_message=False):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    servers=getServers(authToken,user_id,chat_id)
    if not servers is None:
        currentStations=""

        for s in sorted(servers, key=lambda item: item['name']):
            sessionResponse=requests.get(
                "https://services.drova.io/session-manager/sessions",
                params={"server_id": s["uuid"],"limit":1},
                headers={"X-Auth-Token": authToken},
            )         
            session=None
            if sessionResponse.status_code == 200:
                sessions = sessionResponse.json()
                if len(sessions)>0:
                    #print (sessions)
                    session=sessions['sessions'][0]

            ipResponse=requests.get(
                "https://services.drova.io/server-manager/serverendpoint/list/"+s['uuid'],
                params={"server_id": s["uuid"],"limit":1},
                headers={"X-Auth-Token": authToken},
            )         
            externalIps=[]
            internalIps=[]
            if ipResponse.status_code == 200:
                ips = ipResponse.json()
                if len(ips)>0:
                    for ip in ips:
                        if isRfc1918Ip(ip['ip']):
                            internalIps.append(ip)
                        else:
                            externalIps.append(ip)

            trial=""
            if  'groups_list' in s and "Free trial volunteers" in s['groups_list']:
                trial=" (Trial)"

            if currentStations!="":
                currentStations+="\r\n\r\n"
            currentStations+=formatStationName( s,session) +f"{trial}:"
            currentStations+=f"\r\n {s['city_name']}"

            if len(externalIps)>0:
                currentStations+="\r\n Внешние адреса:"
                for ip in sorted(externalIps, key=lambda item: item['ip']) :
                    city=getCityByIP(ip['ip'],"")
                    org= getOrgByIP(ip['ip'],"")
                    if len(org)>0:
                        org=f", {org[0:20]}"
                    if city!="":
                        city=f"({city[0:15]}{org})"
                    currentStations+=f"\r\n <code>{ip['ip']}</code>:{ip['base_port']} {city}"
            if len(internalIps)>0:
                currentStations+="\r\n Внутренние адреса:"
                for ip in sorted(internalIps, key=lambda item: item['ip']) :
                    currentStations+=f"\r\n <code>{ip['ip']}</code>:{ip['base_port']}"
        

        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        update_text = f"Update ({current_time})"
        update_callback_data = "update_stationsinfo"

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
                    text=currentStations,
                    reply_markup=reply_markup,
                    parse_mode=telegram.ParseMode.HTML,
                )
            except telegram.TelegramError as e:
                pass

        else:
            bot.send_message(chat_id=chat_id, 
                text=currentStations,
                    reply_markup=reply_markup,
                parse_mode=telegram.ParseMode.HTML,
            )
    else:
        bot.send_message(chat_id=chat_id, text=f"Error")  


def handle_disabled(update,context, edit_message=False):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    servers=getServers(authToken,user_id,chat_id)
    if not servers is None:

        currentProducts=""

        for s in servers:
            products=getServerProducts(authToken,user_id,s['uuid'])
            if not products is None and len(products)>0:
                currentServerProducts=""
                for product in products:
                    if not product['published'] or not product['enabled'] or not product['available']:
                        _,info=getProductState(product)
                        currentServerProducts+=product['title']+info+"\r\n"
                if currentServerProducts!="":
                    currentProducts+=f"{formatStationName(s,None)}:\r\n{currentServerProducts}"

        if currentProducts=="":
            currentProducts="all products fine"

        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        update_text = f"Update ({current_time})"
        update_callback_data = "update_disabled"

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
                    text=currentProducts,
                    reply_markup=reply_markup,
                    parse_mode=telegram.ParseMode.HTML,
                )
            except telegram.TelegramError as e:
                pass

        else:
            bot.send_message(chat_id=chat_id, 
                text=currentProducts,
                    reply_markup=reply_markup,
                parse_mode=telegram.ParseMode.HTML,
            )
    else:
        bot.send_message(chat_id=chat_id, text=f"Error")                        

# Define the callback function for the update button
def update_current_callback(update, context):
    query = update.callback_query
    chat_id = query.message.chat_id

    if "update_current" in query.data:
        # Modify the original message 
        handle_current(query, context, edit_message=True)
        query.answer()
    else:
        bot.send_message(
            chat_id=chat_id, text="Sorry, I don't understand that command."
        )
        query.answer()


def formatStationName(station,session):
    station_name=station["name"]
    if station["state"]!="LISTEN"and station["state"]!= "HANDSHAKE" and station["state"]!="BUSY" :
        station_name=f"<s>{station_name}</s>"
    
    if not station['published']:
        station_name=f"<em>{station_name}</em>"

    if not session is None:
        if session["status"]=="ACTIVE" or  station["state"]== "HANDSHAKE":
          station_name=f"<strong>{station_name}</strong>"   

    return station_name     


# Set up the command handler for the '/current' command
def handle_current(update, context, edit_message=False):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    servers=getServers(authToken,user_id,chat_id)
    if not servers is None:
        
        currentSessions=""

        for s in sorted(servers, key=lambda item: item['name']):
            sessionResponse=requests.get(
                "https://services.drova.io/session-manager/sessions",
                params={"server_id": s["uuid"],"limit":1},
                headers={"X-Auth-Token": authToken},
            )         

            if sessionResponse.status_code == 200:
                sessions = sessionResponse.json()

                if len(sessions["sessions"])>0:
                    
                    for session in sessions["sessions"]:
                        game_name = products_data.get(session["product_id"], "Unknown")
                        if game_name == "Unknown":
                            products_data_update(update, context)
                            game_name = products_data.get(session["product_id"], "Unknown")       

                        trial=""
                        if session['billing_type']=="trial":
                            trial=" | Trial"

                        created_on=datetime.datetime.fromtimestamp(session["created_on"] / 1000.0   ).strftime("%d.%m %H:%M")
                        clientCityRange=calcRangeByIp(s,session["creator_ip"])
                        if clientCityRange==-1:
                            clientCityRange=""
                        else:
                            clientCityRange=f" {clientCityRange} км |"
                        currentSessions += formatStationName( s,session) +" | "+game_name+ trial +" | "+getCityByIP(session["creator_ip"])+f" |{clientCityRange} "+created_on+" ("+formatDuration(getSessionDuration(session))+")\r\n"
                else:
                    currentSessions += formatStationName(s,None) +" no sessions\r\n"

        if currentSessions!="":
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            update_text = f"Update ({current_time})"
            update_callback_data = "update_current"

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
                        text=currentSessions,
                        reply_markup=reply_markup,
                        parse_mode=telegram.ParseMode.HTML,
                    )
                except telegram.TelegramError as e:
                    pass

            else:
                bot.send_message(chat_id=chat_id, 
                    text=currentSessions,
                        reply_markup=reply_markup,
                    parse_mode=telegram.ParseMode.HTML,
                )
    else:
        bot.send_message(chat_id=chat_id, text=f"Error")




# Set up the command handler for the '/station' command
def handle_station(update, context):
    chat_id = update.message.chat_id
    
    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return

    # If the user provided an ID, update the params with the new station ID
    if len(context.args) > 0:
        station_id = context.args[0]
        setSelectedStationID(chat_id,station_id)
        # Send a message to the user confirming the update
        bot.send_message(chat_id=chat_id, text=f"Station ID updated to {station_id}.")
    else:
        user_id = persistentData['userIDs'].get(str(chat_id), None)

        # Retrieve a list of available server IDs from the API
        response = requests.get(
            "https://services.drova.io/server-manager/servers",
            params={"user_id": user_id},
            headers={"X-Auth-Token": authToken},
        )

        if response.status_code == 200:
            servers = response.json()

            stationNames={}
            for s in servers:
                stationNames[s['uuid']]=s['name']
            storeStationNames(chat_id,stationNames)

            servers.append({'uuid':"-","name":"all"})

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

def handle_limit(update, context):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    if len(context.args) > 0:
        limit = context.args[0]
        setLimit(chat_id,limit)
        # Send a message to the user confirming the update
        bot.send_message(chat_id=chat_id, text=f"Limit updated to {limit}.")
    else:
        bot.send_message(chat_id=chat_id, text=f"add limit number to command")

def filterSessionsByProductAndDays(stationSessions,productID,daysLimit=30):
    monthProductSessions=[]
    monthBack=datetime.datetime.now()-datetime.timedelta(days=daysLimit)
    for session in stationSessions:
        if daysLimit>0:
            if session['product_id']==productID and session['created_on']/1000>monthBack.timestamp():
                monthProductSessions.append(session)
        else:
            if session['product_id']==productID:
                monthProductSessions.append(session)
    return monthProductSessions

def calcSessionsDuration(sessions):
    duration=0
    for session in sessions:
        duration+=getSessionDuration(session)
    return duration

def handle_dumpstantionsproducts(update,context):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")

    user_id = persistentData['userIDs'].get(str(chat_id), None)

    withTime=False
    daysLimit=0
    if(update['message']['text']).lower()=="/dumpstationsproductswithtime" :
        withTime=True
        allsessions={}
    if(update['message']['text']).lower()=="/dumpstationsproductsmonth" :
        withTime=True
        allsessions={}
        daysLimit=30



    servers=getServers(authToken,user_id,chat_id)
    if not servers is None:

        columns={}
        allProducts={}
        firstSessionDate=datetime.datetime.now()
        LastSessionDate=datetime.datetime.strptime("01/01/2020", "%d/%m/%Y")

        for s in servers:
            columns[s['name']]=0

            products=getServerProducts(authToken,user_id,s['uuid'])
            if not products is None and len(products)>0:
                for product in products:
                    if not product['title'] in allProducts:
                        allProducts[product['title']] ={}
                    allProducts[product['title']][s['uuid']]=product

            if withTime:
                sessions=getSessions(authToken,s['uuid'])
                if not sessions is None:
                    allsessions[s['uuid']]=sessions
                if daysLimit==0:
                    for session in sessions:
                        sessionStart=datetime.datetime.fromtimestamp(session["created_on"] / 1000.0)
                        if sessionStart>LastSessionDate:
                            LastSessionDate=sessionStart
                        if sessionStart<firstSessionDate:
                            firstSessionDate=sessionStart

        
        if len(allProducts.keys())>0:

            colN=2
           
            wb = Workbook()
            ws = wb.active

            ws.cell(row=1,column=1).value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws.cell(row=1,column=1).alignment = Alignment(horizontal='center')

            if  withTime:
                if daysLimit>0:
                    ws.cell(row=1,column=1).value=ws.cell(row=1,column=1).value+f" данные за {daysLimit} дней"
                else:
                    ws.cell(row=1,column=1).value=ws.cell(row=1,column=1).value+f" данные с {firstSessionDate.strftime('%Y-%m-%d')} по {LastSessionDate.strftime('%Y-%m-%d')}"\
                    +"\r\nу разных станций доступно разное количество сессий, дата начала взята с самой старой"
                    ws.cell(row=1,column=1).alignment = Alignment(wrapText=True)

            #for stationName in sorted(columns.keys()):
            for stationID in sorted(persistentData['stationNames'][str(chat_id)].values()):
                ws.cell(row=1,column=colN).value=stationID
                columns[stationID]=colN
                colN+=1


            names=sorted(allProducts.keys())
            for idx, productName in enumerate(names):
                ws.cell(row=idx+2,column=1).value=productName
                for stationID in allProducts[productName].keys():
                    stateError,cellValue=getProductState( allProducts[productName][stationID],"Active")
                    #ws.cell(row=idx+2,column=columns[stationName]).value=state
                    
                    if  withTime:
                        stationSessions=allsessions[stationID]
                        productID=allProducts[productName][stationID]['productId']
                        productSessions=filterSessionsByProductAndDays(stationSessions,productID,daysLimit)
                        cellValue=formatDuration( calcSessionsDuration(productSessions),False)
                        ws.cell(row=idx+2,column=columns[persistentData['stationNames'][str(chat_id)][stationID]]).number_format ="[h]:mm:ss" #'d h:mm:ss'

                    ws.cell(row=idx+2,column=columns[persistentData['stationNames'][str(chat_id)][stationID]]).value=cellValue

                    if stateError:
                        yellow = "00FFFF00"
                        ws.cell(row=idx+2,column=columns[persistentData['stationNames'][str(chat_id)][stationID]]).fill = PatternFill(start_color=yellow, end_color=yellow,fill_type = "solid")

            # добавляем формулы
            if ws.max_row>1:
                lastColumn=ws.max_column+1
                #lastRow=ws.max_row+1

                for row in ws.rows:
                    rowNum=0
                    formula=""
                    for cell in row:
                        rowNum=cell.row
                        if cell.col_idx==2 and rowNum>1:
                            formula=f"=SUM({cell.coordinate}"
                        elif cell.col_idx>2 and rowNum>1:
                            formula+=f"+{cell.coordinate}"

                    if formula!="":
                        formula+=")"
                    ws.cell(row=rowNum,column=lastColumn).value=formula
                    ws.cell(row=rowNum,column=lastColumn).number_format ="[h]:mm:ss" #'d h:mm:ss'

                ws.cell(row=1,column=lastColumn).value="Всего"
                #ws.cell(row=lastRow,column=lastColumn).value="fff"
                #ws.cell(row=lastRow,column=lastColumn-1).value="Итого"

            # подбираем ширину колонок
            if ws.max_row>1:
                dims = {}
                for row in ws.rows:
                    for cell in row:
                        if cell.value:
                            dims[cell.column_letter] = max((dims.get(cell.column_letter, 0), len(str(cell.value))))
                for col, value in dims.items():
                    ws.column_dimensions[col].width = value*1.1
                
                filename=f"productStates{user_id}.xlsx"
                if withTime:
                    filename=f"productStatesWithTime{user_id}.xlsx"
                if daysLimit>0:
                    filename=f"productStatesDays{daysLimit}_{user_id}.xlsx"

                # old sending via tempfile disabled - check!
                #wb.save(filename)
                #bot.send_document(chat_id=chat_id, document=open(filename, "rb"))

                # testing direct sending
                buf = io.BytesIO()
                buf.name = filename
                wb.save(buf)
                buf.seek(0)
                bot.send_document(chat_id=chat_id, document=buf)

        else:
            bot.send_message(chat_id=chat_id, text=f"Error")
    else:
        bot.send_message(chat_id=chat_id, text=f"Error")



def handle_dump(update, context):
    chat_id = update.message.chat_id

    authToken=persistentData['authTokens'].get(str(chat_id), None)
    if authToken is None:
        bot.send_message(chat_id=chat_id, text=f"setup me first")
        return
    
    dumpOnefile=False
    if(update['message']['text']).lower()=="/dumponefile":
        dumpOnefile=True


    # Set up the endpoint URL and request parameters
    url = "https://services.drova.io/session-manager/sessions"


    if len(context.args) == 0:

        user_id = user_id = persistentData['userIDs'].get(str(chat_id), None)

        # Retrieve a list of available server IDs from the API
        servers_response = requests.get(
            "https://services.drova.io/server-manager/servers",
            params={"user_id": user_id},
            headers={"X-Auth-Token": authToken},
        )

        if servers_response.status_code == 200:
            servers = servers_response.json()


            fieldnames = ['Game name','creator_ip','City','RangeKm','ASN','Date','Duration','Start time','Finish time', 'billing_type','status',  'abort_comment', 'client_id','id','uuid',  'server_id', 'merchant_id', 'product_id', 'created_on', 'finished_on', 'score', 'score_reason', 'score_text', 'parent', 'sched_hints']

            if dumpOnefile:
                wb = Workbook()
                ws = wb.active
                #ws.append(fieldnames)

            for s in servers:
                response = requests.get(url, params={"server_id": s["uuid"]}, headers={"X-Auth-Token": authToken})
                if response.status_code == 200:
                    sessions = response.json()["sessions"]
                    for item in sessions:
                        product_id = item.get("product_id")

                        creator_ip = item.get("creator_ip")
                        creator_city= getCityByIP(creator_ip,"X")
                        clientCityRange=calcRangeByIp(s,creator_ip)

                        creator_org= getOrgByIP(creator_ip,"X")

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
                                    seconds=datetime.datetime.utcnow().timestamp() - item["created_on"] / 1000
                                )
                        #duration_str = str(duration).split(".")[0]
                        duration_str =formatDuration( getSessionDuration(item),False)

                        item["Game name"] = game_name
                        item["City"] = creator_city
                        item["ASN"] = creator_org
                        item["Duration"] = duration_str
                        item["Start time"] = start_time
                        item["Finish time"] = finish_time
                        item["Date"] = created_on
                        item["RangeKm"]=clientCityRange


                        if dumpOnefile:
                            item['Station Name']=s['name']
                            item['created_on']= datetime.datetime.fromtimestamp(item["created_on"] / 1000.0   ).strftime("%Y-%m-%d %H:%M:%S")
                            if not item["finished_on"]  is None:
                                item['finished_on']=datetime.datetime.fromtimestamp(item["finished_on"] / 1000.0   ).strftime("%Y-%m-%d %H:%M:%S")

                    csv_file = "sessions-" + s["name"] + ".csv"


                    if not dumpOnefile:
                        # direct send testing
                        try:
                            s = io.StringIO()
                            writer = csv.DictWriter(s, fieldnames=fieldnames)
                            writer.writeheader()
                            writer.writerows(sessions)
                            s.seek(0)
                            buf = io.BytesIO()  
                            buf.write(s.getvalue().encode())
                            buf.seek(0)  
                            buf.name = csv_file
                            bot.send_document(chat_id=chat_id, document=buf)
                        except Exception as e:
                            bot.send_message(chat_id=chat_id, text=f"Error {e} with station {s['name']}")

                        # old sending via tempfile
                        # Write session data to CSV
                        #with open(csv_file, 'w', newline='') as file:
                        #    writer = csv.DictWriter(file, fieldnames=fieldnames)
                        #    writer.writeheader()
                        #    writer.writerows(sessions)
                        #bot.send_document(chat_id=chat_id, document=open(csv_file, "rb"))
                    else:
                        for row in sessions:
                            if ws.max_row==1:
                                ws.append(list(row.keys()))
                            if 'parent' in row:
                                del row['parent']
                            if 'sched_hints' in row:
                                del row['sched_hints']
                            ws.append(list(row.values()))

            if dumpOnefile:
                # подбираем ширину колонок
                if ws.max_row>1:
                    dims = {}
                    for row in ws.rows:
                        for cell in row:
                            if cell.value:
                                dims[cell.column_letter] = max((dims.get(cell.column_letter, 0), len(str(cell.value))))
                    for col, value in dims.items():
                        ws.column_dimensions[col].width = value*1.1
                    
                    # old sending via tempfile disabled - check!
                    #wb.save(f"data{user_id}.xlsx")
                    #bot.send_document(chat_id=chat_id, document=open(f"data{user_id}.xlsx", "rb"))

                    # testing direct sending
                    buf = io.BytesIO()
                    buf.name = f"data{user_id}.xlsx"
                    wb.save(buf)
                    buf.seek(0)
                    bot.send_document(chat_id=chat_id, document=buf)



        else:
            bot.send_message(chat_id=chat_id, text=f"Error: {response.status_code}")

    



def products_data_update(update, context):
    chat_id = update.message.chat_id

    global products_data

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
    setSelectedStationID(chat_id,server_id)

    if server_id=="-":
        message=f"Selected all stations."
    else:
        message=f"Station ID updated to {server_id}."

    bot.answer_callback_query(
        callback_query_id=query.id, text=message
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

    # Add a handler for the '/removeToken' command
    remove_token_handler = telegram.ext.CommandHandler("removeToken", removeAuthToken)
    dispatcher.add_handler(remove_token_handler)

    # Set up the callback query handlers
    update_sessions_handler = telegram.ext.CallbackQueryHandler(
        update_sessions_callback, pattern="^update_sessions"
    )
    dispatcher.add_handler(update_sessions_handler)

    set_server_id_handler = telegram.ext.CallbackQueryHandler(
        set_server_id_callback, pattern="^set_server_id_"
    )
    dispatcher.add_handler(set_server_id_handler)

    # Set up the callback query handlers
    update_current_handler = telegram.ext.CallbackQueryHandler(
        update_current_callback, pattern="^update_current"
    )
    dispatcher.add_handler(update_current_handler)

    # Set up the command handler for the '/current' command
    current_handler = telegram.ext.CommandHandler("current", handle_current)
    dispatcher.add_handler(current_handler)

    # Set up the callback query handlers
    update_disabled_handler = telegram.ext.CallbackQueryHandler(
        update_disabled_callback, pattern="^update_disabled"
    )
    dispatcher.add_handler(update_disabled_handler)

    # Set up the command handler for the '/disabled' command
    disabled_handler = telegram.ext.CommandHandler("disabled", handle_disabled)
    dispatcher.add_handler(disabled_handler)

    # Set up the callback query handlers
    update_stationsinfo_handler = telegram.ext.CallbackQueryHandler(
        update_stationsinfo_callback, pattern="^update_stationsinfo"
    )
    dispatcher.add_handler(update_stationsinfo_handler)

    # Set up the command handler for the '/stationsinfo' command
    stationsinfo_handler = telegram.ext.CommandHandler("stationsInfo", handle_stationsinfo)
    dispatcher.add_handler(stationsinfo_handler)

    # Set up the command handler for the '/start' command
    start_handler = telegram.ext.CommandHandler("start", handle_start)
    dispatcher.add_handler(start_handler)

    # Set up the command handler for the '/station' command
    station_handler = telegram.ext.CommandHandler("station", handle_station)
    dispatcher.add_handler(station_handler)

    # Set up the command handler for the '/limit' command
    limit_handler = telegram.ext.CommandHandler("limit", handle_limit)
    dispatcher.add_handler(limit_handler)

    # Set up the command handler for the '/dumpall' command
    dump_handler = telegram.ext.CommandHandler("dumpall", handle_dump)
    dispatcher.add_handler(dump_handler)

    dump_handler2 = telegram.ext.CommandHandler("dumpOnefile", handle_dump)
    dispatcher.add_handler(dump_handler2)

    dump_stantionsproducts = telegram.ext.CommandHandler("dumpStationsProducts", handle_dumpstantionsproducts)
    dispatcher.add_handler(dump_stantionsproducts)

    dump_stantionsproducts2 = telegram.ext.CommandHandler("dumpStationsProductsWithTime", handle_dumpstantionsproducts)
    dispatcher.add_handler(dump_stantionsproducts2)
    dump_stantionsproducts3 = telegram.ext.CommandHandler("dumpStationsProductsMonth", handle_dumpstantionsproducts)
    dispatcher.add_handler(dump_stantionsproducts3)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
