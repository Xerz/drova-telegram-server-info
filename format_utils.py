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

