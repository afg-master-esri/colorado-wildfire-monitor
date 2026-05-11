import requests, json, datetime, os

NASA_API_KEY  = os.environ["NASA_FIRMS_API_KEY"]
AGOL_USERNAME = os.environ["AGOL_USERNAME"]
AGOL_PASSWORD = os.environ["AGOL_PASSWORD"]
AGOL_LAYER_ID = os.environ["AGOL_LAYER_ID"]

CO_BBOX = "-109.060253,36.992426,-102.041524,41.003444"

# Exactamente las mismas fuentes que NASA FIRMS visor en modo 2 DAYS
# Landsat [30m] + VIIRS (S-NPP, NOAA-20 & NOAA-21) [375m] + MODIS [1km]
FIRMS_SOURCES = [("LANDSAT_NRT",      "Landsat 30m",      2),
    ("VIIRS_SNPP_NRT",   "VIIRS S-NPP",      2),
    ("VIIRS_NOAA20_NRT", "VIIRS NOAA-20",    2),
    ("VIIRS_NOAA21_NRT", "VIIRS NOAA-21",    2),
    ("MODIS_NRT",        "MODIS Aqua+Terra", 2),
]

def log(msg, level="INFO"):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def descargar_focos():
    log("=" * 55)
    log("Colorado Wildfire Monitor — NASA FIRMS 2 DAYS")
    log("Fuentes: Landsat + VIIRS S-NPP/NOAA-20/NOAA-21 + MODIS")
    log("=" * 55)
    todos = []
    for source, nombre, dias in FIRMS_SOURCES:
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
               f"{NASA_API_KEY}/{source}/{CO_BBOX}/{dias}")
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            lineas = resp.text.strip().split("\n")
            if len(lineas) < 2:
                log(f"  {nombre}: sin datos", "WARN"); continue
            cab = lineas[0].split(",")
            n   = len(todos)
            for l in lineas[1:]:
                vals = l.split(",")
                if len(vals) >= 2:
                    f = dict(zip(cab, vals)); f["sensor"] = nombre; todos.append(f)
            log(f"  {nombre} ({dias}d): {len(todos)-n} detecciones")
        except Exception as e:
            log(f"  {nombre}: error - {e}", "ERROR")
    log(f"Total focos descargados: {len(todos)}")
    return todos

def focos_a_esri(focos):
    features = []
    vistos   = set()
    for f in focos:
        try:
            lat = float(f.get("latitude", 0))
            lon = float(f.get("longitude", 0))
            if not (36.99 <= lat <= 41.01 and -109.07 <= lon <= -102.04): continue
            # Deduplicar por posicion y fecha
            clave = f"{round(lat,3)}_{round(lon,3)}_{f.get('acq_date','')}"
            if clave in vistos: continue
            vistos.add(clave)
            features.append({
                "geometry": {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}},
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
    log(f"Focos unicos en Colorado: {len(features)}")
    return features

def obtener_token():
    log("Autenticando ArcGIS Online...")
    resp = requests.post("https://www.arcgis.com/sharing/rest/generateToken",
        data={"username": AGOL_USERNAME, "password": AGOL_PASSWORD,
              "referer": "https://www.arcgis.com", "expiration": 60, "f": "json"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Auth: {data['error']}")
    log("Token OK"); return data["token"]

def obtener_url_servicio(token):
    resp = requests.get(f"https://www.arcgis.com/sharing/rest/content/items/{AGOL_LAYER_ID}",
        params={"token": token, "f": "json"}, timeout=30)
    resp.raise_for_status()
    url = resp.json().get("url", "")
    if not url: raise RuntimeError("No URL del servicio")
    log(f"Servicio: {url}"); return url

def borrar_features(url_svc, token):
    log("Borrando features anteriores...")
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
            data={"features": json.dumps(lote), "token": token, "f": "json"}, timeout=60)
        resp.raise_for_status()
        ok = sum(1 for r in resp.json().get("addResults", []) if r.get("success"))
        total += ok; log(f"  Lote {i//200+1}: {ok}/{len(lote)}")
    log(f"Total publicados: {total}"); return total

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
