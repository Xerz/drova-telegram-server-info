import datetime


def formatDuration(elapsed_time, shortFormat=True):
    if elapsed_time < 3600 and shortFormat:
        minutes, seconds = divmod(elapsed_time, 60)
        return "{:.0f}m:{:.0f}s ".format(minutes, seconds)
    elif elapsed_time < 86400 and shortFormat:
        hours, remainder = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:.0f}h {:.0f}m".format(hours, minutes)
    else:
        days, remainder = divmod(elapsed_time, 86400)
        fullhours = elapsed_time/3600
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if shortFormat:
            return "{:.0f}d {:.0f}h {:.0f}m".format(days, hours, minutes)
        else:
            return "{:02.0f}:{:02.0f}:{:02.0f}".format(fullhours, minutes, seconds)


def getSessionDuration(session):
    if session['finished_on'] is None:
        duration = (datetime.datetime.now().timestamp() - session['created_on']/1000)
    else:
        duration = (session['finished_on'] - session['created_on'])/1000
    return duration

