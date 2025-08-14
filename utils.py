import datetime

def format_duration(elapsed_time, short_format=True):
    td = datetime.timedelta(seconds=elapsed_time)
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if short_format:
        if elapsed_time < 3600:
            return f"{minutes}m:{seconds}s"
        elif elapsed_time < 86400:
            return f"{hours}h {minutes}m"
        else:
            return f"{days}d {hours}h {minutes}m"
    total_hours = int(td.total_seconds() // 3600)
    return f"{total_hours:02}:{minutes:02}:{seconds:02}"

def get_session_duration(session):
    finished = session.get("finished_on")
    created = session["created_on"]
    if finished is None:
        duration = datetime.datetime.now().timestamp() - created / 1000
    else:
        duration = (finished - created) / 1000
    return duration