import json

persistentData = {
    "authTokens": {},
    "userIDs": {},
    "limits": {},
    "selectedStations": {},
    "stationNames": {},
}

try:
    with open("persistentData.json", 'r') as f:
        persistentData = json.load(f)
except Exception:
    pass

def storePersistentData():
    try:
        with open("persistentData.json", 'w') as f:
            json.dump(persistentData, f, indent=4)
    except Exception:
        pass


def setUserID(chatID, userID):
    if 'userIDs' not in persistentData:
        persistentData['userIDs'] = {}
    persistentData['userIDs'][str(chatID)] = userID
    storePersistentData()


def setAuthToken(chatID, authToken):
    if 'authTokens' not in persistentData:
        persistentData['authTokens'] = {}

    if authToken == "-" and str(chatID) in persistentData['authTokens']:
        del persistentData['authTokens'][str(chatID)]
        storePersistentData()
        return True
    elif authToken != "-":
        persistentData['authTokens'][str(chatID)] = authToken
        storePersistentData()


def getAuthTokensByChatID(chatID):
    return persistentData['authTokens'].get(str(chatID), None)


def setSelectedStationID(chatID, stationID):
    if 'selectedStations' not in persistentData:
        persistentData['selectedStations'] = {}
    if stationID == "-" and str(chatID) in persistentData['selectedStations']:
        del persistentData['selectedStations'][str(chatID)]
    elif stationID != "-":
        persistentData['selectedStations'][str(chatID)] = stationID
    storePersistentData()


def setLimit(chatID, limit):
    if 'limits' not in persistentData:
        persistentData['limits'] = {}
    persistentData['limits'][str(chatID)] = int(limit)
    storePersistentData()


def storeStationNames(chatID, stations):
    if 'stationNames' not in persistentData:
        persistentData['stationNames'] = {}
    persistentData['stationNames'][str(chatID)] = stations
    storePersistentData()


def getStationNamesWithID(chatID):
    stations = {}
    if 'stationNames' in persistentData and str(chatID) in persistentData['stationNames']:
        for id, name in persistentData['stationNames'][str(chatID)].items():
            stations[name] = id
    return stations
