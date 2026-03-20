import ipaddress
import math
import os
import shutil
import urllib.request

import geoip2.database


ip_reader = None
ip_isp_reader = None

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_GEODB_URLS = {
    'GeoLite2-City.mmdb': 'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb',
    'GeoLite2-ASN.mmdb': 'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb',
}


def _getGeodbPath(filename):
    return os.path.join(_BASE_DIR, filename)


def _downloadGeodb(filename):
    file_path = _getGeodbPath(filename)
    temp_path = f'{file_path}.download'
    try:
        with urllib.request.urlopen(_GEODB_URLS[filename], timeout=15) as response, open(temp_path, 'wb') as temp_file:
            shutil.copyfileobj(response, temp_file)
        os.replace(temp_path, file_path)
        return True
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return False


def tryLoadGeodb():
    global ip_reader, ip_isp_reader
    city_db_path = _getGeodbPath('GeoLite2-City.mmdb')
    asn_db_path = _getGeodbPath('GeoLite2-ASN.mmdb')

    if not os.path.exists(city_db_path):
        _downloadGeodb('GeoLite2-City.mmdb')
    if not os.path.exists(asn_db_path):
        _downloadGeodb('GeoLite2-ASN.mmdb')

    if ip_reader is None:
        try:
            ip_reader = geoip2.database.Reader(city_db_path)
        except Exception:
            ip_reader = None

    if ip_isp_reader is None:
        try:
            ip_isp_reader = geoip2.database.Reader(asn_db_path)
        except Exception:
            ip_isp_reader = None


def isRfc1918Ip(ip):
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
        return False


def haversineDistance(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return -1
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    earth_radius = 6371.0
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = earth_radius * c
    return distance


def calcRangeByIp(station, clientIp):
    if ip_reader is None:
        tryLoadGeodb()
    if ip_reader is None:
        return -1
    cityInfo = None
    try:
        cityInfo = ip_reader.city(clientIp).location
    except Exception:
        pass
    if cityInfo is not None:
        clientLatitude = cityInfo.latitude
        clientLongitude = cityInfo.longitude
        return round(haversineDistance(station['latitude'], station['longitude'], clientLatitude, clientLongitude), 1)
    return -1


def getCityByIP(creator_ip, defValue=""):
    if ip_reader is None:
        tryLoadGeodb()
    if ip_reader is None:
        return defValue
    creator_city = defValue
    try:
        creator_city = ip_reader.city(creator_ip).city.name
    except Exception:
        pass
    if creator_city is None:
        creator_city = defValue
    return creator_city


def getOrgByIP(creator_ip, defValue=""):
    if ip_isp_reader is None:
        tryLoadGeodb()
    if ip_isp_reader is None:
        return defValue
    creator_org = defValue
    try:
        creator_org = ip_isp_reader.asn(creator_ip).autonomous_system_organization
    except Exception:
        pass
    if creator_org is None:
        creator_org = defValue
    return creator_org
