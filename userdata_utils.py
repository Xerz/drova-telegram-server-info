import json
import requests
from drova_utils import DrovaClient
class PersistentDataManager:
    def __init__(self):
        self.persistentData = {
            "authTokens": {},
            "userIDs": {},
            "limits": {},
            "selectedStations": {},
            "stationNames": {},
        }

        self.products_data = {}
        self.loadPersistentData()

    def loadPersistentData(self):
        # Load the auth tokens from a JSON file
        try:
            with open("persistentData.json", 'r') as f:
                self.persistentData = json.load(f)
        except:
            pass
        # Load the products data from a JSON file
        try:
            with open("products.json", "r") as f:
                self.products_data = json.load(f)
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
    
    def getProductData(self, product_id):
        return self.products_data.get(product_id, "Unknown game")
        
    def updateProductsData(self):
        products_data_len_old = len(self.products_data)

        products_data_new = DrovaClient.getProductsData()
        if products_data_new:
            self.products_data = products_data_new

            products_data_len_new = len(self.products_data)

            with open("products.json", "w") as f:
                f.write(json.dumps(self.products_data))

            return products_data_len_old, products_data_len_new
        return products_data_len_old, None

    def getPersistentData(self):
        return self.persistentData
