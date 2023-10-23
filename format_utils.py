from session_utils import getSessionDuration
from ip_utils import IpTools
import datetime

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

def generate_session_text(limit, i, game_name, server_name, session, ip_tool):

    creator_ip = session.get("creator_ip", "N/A")
    creator_city = ip_tool.getCityByIP(creator_ip,"X")
    creator_org = ip_tool.getOrgByIP(creator_ip,"X")

    client_id = session.get("client_id", "xxxxxx")[-6:]

    start_time = datetime.datetime.fromtimestamp(
                session["created_on"] / 1000.0
            ).strftime("%H:%M:%S")
    finish_time = session["finished_on"]
    duration_str =formatDuration(getSessionDuration(session))
    score_text = session.get("score_text", "N/A")


    message = f"{limit - i + 1}. <strong>{game_name}</strong>\n"
    message += server_name
    message += f"<code>{creator_ip}</code> <code>{client_id}</code>\n"

    message += f"{creator_city} {creator_org}\n{start_time}-{finish_time} ({duration_str})\n"

    message += f"Feedback: {score_text}\n" if score_text is not None else ""

    message += f"{session.get('billing_type', 'N/A')} {session['status'].lower()}\n\n"

    return message

def generate_current_station_text(s,session,trial,internalIps,externalIps,ip_tool):
    currentStations=formatStationName(s,session) +f"{trial}:"
    currentStations+=f"\r\n {s['city_name']}"

    if len(externalIps)>0:
        currentStations+="\r\n Внешние адреса:"
        for ip in sorted(externalIps, key=lambda item: item['ip']) :
            city=ip_tool.getCityByIP(ip['ip'],"")
            org= ip_tool.getOrgByIP(ip['ip'],"")
            if len(org)>0:
                org=f", {org[0:20]}"
            if city!="":
                city=f"({city[0:15]}{org})"
            currentStations+=f"\r\n <code>{ip['ip']}</code>:{ip['base_port']} {city}"
    if len(internalIps)>0:
        currentStations+="\r\n Внутренние адреса:"
        for ip in sorted(internalIps, key=lambda item: item['ip']) :
            currentStations+=f"\r\n <code>{ip['ip']}</code>:{ip['base_port']}"
    return currentStations