import requests
class DrovaClient:
    def __init__(self):
        pass

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
    
    def getSessions(authToken, server_id):
        response = requests.get("https://services.drova.io/session-manager/sessions", params={"server_id": server_id}, headers={"X-Auth-Token": authToken})
        if response.status_code == 200:
            return response.json()["sessions"]   
        return None

    def getSessions(authToken, server_id, limit):
        response = requests.get("https://services.drova.io/session-manager/sessions", params={"server_id": server_id, "limit": limit}, headers={"X-Auth-Token": authToken})
        if response.status_code == 200:
            return response.json()["sessions"]   
        return None