"""
Colorado Wildfire Monitor
Lee directamente del Feature Service oficial NASA FIRMS
Identico al visor nasa firms - mismos datos, misma fuente
"""
import requests, json, datetime, os

AGOL_USERNAME = os.environ["AGOL_USERNAME"]
AGOL_PASSWORD = os.environ["AGOL_PASSWORD"]
AGOL_LAYER_ID = os.environ["AGOL_LAYER_ID"]

# Bounding box Colorado
CO_BBOX_GEOM = "-109.060253,36.992426,-102.041524,41.003444"
CO_LAT_MIN, CO_LAT_MAX = 36.99, 41.01
CO_LON_MIN, CO_LON_MAX = -109.07, -102.04

FIRMS_REST_SERVICES = [
    {
        "nombre": "VIIRS SNPP NRT",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/8c41a3efcb377394cacd774d0d2906b1/VIIRS_SNPP_NRT/{bbox}/1",
        "sensor": "VIIRS S-NPP"
    },
    {
        "nombre": "VIIRS NOAA-20 NRT",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/8c41a3efcb377394cacd774d0d2906b1/VIIRS_NOAA20_NRT/{bbox}/1",
        "sensor": "VIIRS NOAA-20"
    },
    {
        "nombre": "VIIRS NOAA-21 NRT",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/8c41a3efcb377394cacd774d0d2906b1/VIIRS_NOAA21_NRT/{bbox}/1",
        "sensor": "VIIRS NOAA-21"
    },
    {
        "nombre": "MODIS NRT",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/8c41a3efcb377394cacd774d0d2906b1/MODIS_NRT/{bbox}/1",
        "sensor": "MODIS"
    },
    {
        "nombre": "Landsat NRT",
        "url": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/8c41a3efcb377394cacd774d0d2906b1/LANDSAT_NRT/{bbox}/1",
        "sensor": "Landsat"
    },
]

def log(msg, level="INFO"):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def descargar_focos():
    log("=" * 55)
    log("Colorado Wildfire Monitor - NASA FIRMS 24HRS")
    log("=" * 55)
    todos = []
    for svc in FIRMS_REST_SERVICES:
        url = svc["url"].replace("{bbox}", CO_BBOX_GEOM)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            lineas = resp.text.strip().split("\n")
            if len(lineas) < 2:
                log(f"  {svc['nombre']}: sin datos", "WARN"); continue
            cab = lineas[0].split(",")
            n   = len(todos)
            for l in lineas[1:]:
                vals = l.split(",")
                if len(vals) >= 2:
                    f = dict(zip(cab, vals))
                    f["sensor"] = svc["sensor"]
                    todos.append(f)
            log(f"  {svc['nombre']}: {len(todos)-n} detecciones")
        except Exception as e:
            log(f"  {svc['nombre']}: error - {e}", "WARN")
    log(f"Total focos: {len(todos)}")
    return todos

def focos_a_esri(focos):
    features = []
    vistos   = set()
    for f in focos:
        try:
            lat = float(f.get("latitude", 0))
            lon = float(f.get("longitude", 0))
            if not (CO_LAT_MIN <= lat <= CO_LAT_MAX and
                    CO_LON_MIN <= lon <= CO_LON_MAX): continue
            clave = f"{round(lat,3)}_{round(lon,3)}_{f.get('acq_date','')}"
            if clave in vistos: continue
            vistos.add(clave)
            features.append({
                "geometry": {"x": lon, "y": lat,
                             "spatialReference": {"wkid": 4326}},
                "attributes": {
                    "sensor":      f.get("sensor", ""),
                    "bright_ti4":  f.get("bright_ti4", f.get("brightness", "")),
                    "acq_date":    f.get("acq_date", ""),
                    "acq_time":    f.get("acq_time", ""),
                    "confidence":  f.get("confidence", ""),
                    "frp":         f.get("frp", ""),
                    "daynight":    f.get("daynight", ""),
                    "estado":      "Colorado",
                    "actualizado": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                }
            })
        except: continue
    log(f"Focos unicos Colorado: {len(features)}")
    return features

def obtener_token():
    log("Autenticando ArcGIS Online...")
    resp = requests.post(
        "https://www.arcgis.com/sharing/rest/generateToken",
        data={"username": AGOL_USERNAME, "password": AGOL_PASSWORD,
              "referer": "https://www.arcgis.com", "expiration": 60,
              "f": "json"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Auth: {data['error']}")
    log("Token OK"); return data["token"]

def obtener_url_servicio(token):
    resp = requests.get(
        f"https://www.arcgis.com/sharing/rest/content/items/{AGOL_LAYER_ID}",
        params={"token": token, "f": "json"}, timeout=30)
    resp.raise_for_status()
    url = resp.json().get("url", "")
    if not url: raise RuntimeError("No URL del servicio")
    log(f"Servicio: {url}"); return url

def borrar_features(url_svc, token):
    log("Borrando anteriores...")
    resp = requests.post(f"{url_svc}/0/deleteFeatures",
        data={"where": "1=1", "token": token, "f": "json"}, timeout=30)
    resp.raise_for_status()
    log(f"Borrados: {len(resp.json().get('deleteResults', []))}")

def publicar_features(url_svc, token, features):
    if not features: log("Sin focos.", "WARN"); return 0
    log(f"Publicando {len(features)} features...")
    total = 0
    for i in range(0, len(features), 200):
        lote = features[i:i+200]
        resp = requests.post(f"{url_svc}/0/addFeatures",
            data={"features": json.dumps(lote), "token": token,
                  "f": "json"}, timeout=60)
        resp.raise_for_status()
        ok = sum(1 for r in resp.json().get("addResults", []) if r.get("success"))
        total += ok; log(f"  Lote {i//200+1}: {ok}/{len(lote)}")
    log(f"Total: {total}"); return total

def main():
    focos    = descargar_focos()
    features = focos_a_esri(focos)
    token    = obtener_token()
    url_svc  = obtener_url_servicio(token)
    borrar_features(url_svc, token)
    n = publicar_features(url_svc, token, features)
    log("=" * 55)
    log(f"COMPLETADO - {n} focos en ArcGIS Online")
    log("=" * 55)

if __name__ == "__main__":
    main()
