import geoip2.database
import ipaddress
import math

class IpTools:
    def __init__(self, CityFile="GeoLite2-City.mmdb", ASNFile="GeoLite2-ASN.mmdb"):
        try:
            self.ip_reader = geoip2.database.Reader(CityFile)
            self.ip_isp_reader = geoip2.database.Reader(ASNFile)
        except:
            pass
    
    def isRfc1918Ip(self, ip):
        try:
            ip = ipaddress.ip_address(ip)
            rfc1918Ranges = [
                ipaddress.ip_network('10.0.0.0/8'),
                ipaddress.ip_network('172.16.0.0/12'),
                ipaddress.ip_network('192.168.0.0/16'),
            ]
            for rfcRange in rfc1918Ranges:
                if ip in rfcRange:
                    return True
            return False
        except ValueError:
            # Invalid IP address format
            return False
    
    def getCityByIP(self, creator_ip, defValue=""):
        if self.ip_reader==None:
            self.tryLoadGeodb()
        if self.ip_reader==None:
            return defValue

        creator_city=defValue
        try:
            creator_city = self.ip_reader.city(creator_ip).city.name
        except:
            pass
        if creator_city is None:
            creator_city = defValue
        return creator_city

    def getOrgByIP(self, creator_ip, defValue=""):
        if self.ip_isp_reader==None:
            self.tryLoadGeodb()
        if self.ip_isp_reader==None:
            return defValue

        creator_org = defValue
        try:
            creator_org = self.ip_isp_reader.asn(creator_ip).autonomous_system_organization
        except:
            pass
        if creator_org is None:
            creator_org = defValue
        return creator_org

    def haversineDistance(lat1, lon1, lat2, lon2):
        """
        Calculate the great-circle distance between two points on the Earth's surface
        specified in decimal degrees of latitude and longitude.

        :param lat1: Latitude of the first point in degrees.
        :param lon1: Longitude of the first point in degrees.
        :param lat2: Latitude of the second point in degrees.
        :param lon2: Longitude of the second point in degrees.
        :return: The distance in kilometers.
        """

        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return -1

        # Convert latitude and longitude from degrees to radians
        lat1 = math.radians(lat1)
        lon1 = math.radians(lon1)
        lat2 = math.radians(lat2)
        lon2 = math.radians(lon2)

        # Radius of the Earth in kilometers
        earth_radius = 6371.0

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        # Calculate the distance
        distance = earth_radius * c

        return distance


    def calcRangeByIp(self, station, clientIp):
        if self.ip_reader==None:
            self.tryLoadGeodb()
        if self.ip_reader==None:
            return -1

        cityInfo=None
        try:
            cityInfo = self.ip_reader.city(clientIp).location
        except:
            pass

        if cityInfo!=None:
            clientLatitude=cityInfo.latitude
            clientLongitude=cityInfo.longitude
            return round(self.haversineDistance(station['latitude'],station['longitude'],clientLatitude,clientLongitude),1)

        return -1