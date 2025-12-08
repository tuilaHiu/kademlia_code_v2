import geoip2.database

reader = geoip2.database.Reader('GeoLite2-Country.mmdb')

def get_country_from_ip(ip_address: str) -> str:
    try:
        response = reader.country(ip_address)
        return response.country.iso_code  # VD: 'US', 'VN'
    except Exception:
        return "UNKNOWN"