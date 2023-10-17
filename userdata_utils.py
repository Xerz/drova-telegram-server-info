import json

class PersistentDataManager:
    def __init__(self):
        self.persistentData = {
            "authTokens": {},
            "userIDs": {},
            "limits": {},
            "selectedStations": {},
            "stationNames": {},
        }
        self.loadPersistentData()

    def loadPersistentData(self):
        # Load the auth tokens from a JSON file
        try:
            with open("persistentData.json", 'r') as f:
                self.persistentData = json.load(f)
        except:
            pass

    def storePersistentData(self):
        try:
            with open("persistentData.json", 'w') as f:
                json.dump(self.persistentData, f, indent=4)
        except:
            pass

    def setUserID(self, chatID, userID):
        if 'userIDs' not in self.persistentData:
            self.persistentData['userIDs'] = {}
        self.persistentData['userIDs'][str(chatID)] = userID
        self.storePersistentData()

    def setAuthToken(self, chatID, authToken):
        if 'authTokens' not in self.persistentData:
            self.persistentData['authTokens'] = {}

        if authToken == "-" and str(chatID) in self.persistentData['authTokens']:
            del self.persistentData['authTokens'][str(chatID)]
            self.storePersistentData()
            return True
        elif authToken != "-":
            self.persistentData['authTokens'][str(chatID)] = authToken
            self.storePersistentData()

    def getAuthTokensByChatID(self, chatID):
        return self.persistentData['authTokens'].get(str(chatID), None)

    def setSelectedStationID(self, chatID, stationID):
        if 'selectedStations' not in self.persistentData:
            self.persistentData['selectedStations'] = {}
        if stationID == "-" and str(chatID) in self.persistentData['selectedStations']:
            del self.persistentData['selectedStations'][str(chatID)]
        elif stationID != "-":
            self.persistentData['selectedStations'][str(chatID)] = stationID
        self.storePersistentData()

    def setLimit(self, chatID, limit):
        if 'limits' not in self.persistentData:
            self.persistentData['limits'] = {}
        self.persistentData['limits'][str(chatID)] = int(limit)
        self.storePersistentData()

    def storeStationNames(self, chatID, stations):
        if 'stationNames' not in self.persistentData:
            self.persistentData['stationNames'] = {}
        self.persistentData['stationNames'][str(chatID)] = stations
        self.storePersistentData()

    def getUserID(self, chatID):
        return self.persistentData['userIDs'].get(str(chatID), None)
    
    def getStationName(self, chatID, stationID):
        if str(chatID) in self.persistentData['stationNames'] and stationID in self.persistentData['stationNames'][str(chatID)]:
            return self.persistentData['stationNames'][str(chatID)][stationID]
        else:
            return ""
        
    def getLimit(self, chatID):
        return self.persistentData['limits'].get(str(chatID), 5)
    
    def getSelectedStation(self, chatID):
        return self.persistentData['selectedStations'].get(str(chatID), None)
    
    def getStationNames(self, chatID):
        return self.persistentData['stationNames'].get(str(chatID), None)
    
    def getPersistentData(self):
        return self.persistentData
