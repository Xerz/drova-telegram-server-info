import datetime
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

def getSessionDuration(session):
    if session['finished_on'] is None:
        duration=(datetime.datetime.now().timestamp()-session['created_on']/1000)
    else:
        duration=(session['finished_on']-session['created_on'])/1000
    return duration