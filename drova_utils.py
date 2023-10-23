import requests
class DrovaClient:
    def __init__(self):
        pass

    @staticmethod
    def getProductsData():
        response = requests.get(
            "https://services.drova.io/product-manager/product/listfull2",
            params={},
            headers={},
        )

        if response.status_code == 200:
            games = response.json()

            products_data = {}
            for game in games:
                products_data[game["productId"]] = game["title"]
            return products_data
        else:
            return None
    
    @staticmethod
    def getAccountInfo(token):
        accountResp = requests.get(
        "https://services.drova.io/accounting/myaccount",
        headers={"X-Auth-Token": token},
    )
        if accountResp.status_code == 200:
            accountInfo = accountResp.json()
            if('uuid' in accountInfo):
                return accountInfo
            return None
        return None
    
    @staticmethod
    def getSessions(authToken, server_id):
        response = requests.get("https://services.drova.io/session-manager/sessions", params={"server_id": server_id}, headers={"X-Auth-Token": authToken})
        if response.status_code == 200:
            return response.json()["sessions"]   
        return None

    @staticmethod
    def getSessions(authToken, server_id, limit):
        response = requests.get("https://services.drova.io/session-manager/sessions", params={"server_id": server_id, "limit": limit}, headers={"X-Auth-Token": authToken})
        if response.status_code == 200:
            return response.json()["sessions"]   
        return None
    
    @staticmethod
    def getServers(authToken,user_id,chat_id):
        response = requests.get(
        "https://services.drova.io/server-manager/servers",
        params={"user_id": user_id},
        headers={"X-Auth-Token": authToken},
        )
        if response.status_code == 200:
            return response.json()
        print(response.status_code)
        return None
    
    @staticmethod
    def getServerProducts(authToken,user_id,server_id):
        response = requests.get(
            "https://services.drova.io/server-manager/serverproduct/list4edit2/"+server_id,
            params={"user_id": user_id},
            headers={"X-Auth-Token": authToken},
        )
        if response.status_code == 200:
            return response.json()
    