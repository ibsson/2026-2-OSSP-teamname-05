import httpx
import os
from dotenv import load_dotenv

load_dotenv()
TMAP_API_KEY = os.getenv("TMAP_API_KEY") # [cite: 34]
TMAP_URL = "https://apis.openapi.sk.com/tmap/routes?version=1&format=json"

async def get_tmap_route_info(s_lat, s_lon, e_lat, e_lon):
    headers = {"appKey": TMAP_API_KEY, "Content-Type": "application/json"}
    payload = {
        "startX": s_lon, "startY": s_lat,
        "endX": e_lon, "endY": e_lat,
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "searchOption": "0", "trafficInfo": "Y"
    }

    async with httpx.AsyncClient() as client: # [cite: 29, 32]
        try:
            response = await client.post(TMAP_URL, json=payload, headers=headers, timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                properties = data['features'][0]['properties']
                
                path_coordinates = []
                for feature in data['features']:
                    geometry = feature.get('geometry')
                    if geometry and geometry['type'] == "LineString":
                        path_coordinates.extend(geometry['coordinates'])
                
                return {
                    "time": properties['totalTime'],
                    "distance": properties['totalDistance'],
                    "path": path_coordinates
                }
            return None
        except Exception:
            return None