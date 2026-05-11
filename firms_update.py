import requests, json, datetime, os, time

NASA_API_KEY  = os.environ["NASA_FIRMS_API_KEY"]
AGOL_USERNAME = os.environ["AGOL_USERNAME"]
AGOL_PASSWORD = os.environ["AGOL_PASSWORD"]
AGOL_LAYER_ID = os.environ["AGOL_LAYER_ID"]

CO_BBOX    = "-109.060253,36.992426,-102.041524,41.003444"
CO_LAT_MIN, CO_LAT_MAX = 36.99, 41.01
CO_LON_MIN, CO_LON_MAX = -109.07, -102.04

FIRMS_SOURCES = [
    ("LANDSAT_NRT",      "Landsat 30m",      2),
    ("VIIRS_SNPP_NRT",   "VIIRS S-NPP",      1),
    ("VIIRS_NOAA20_NRT", "VIIRS NOAA-20",    1),
    ("VIIRS_NOAA21_NRT", "VIIRS NOAA-21",    1),
    ("MODIS_NRT",        "MODIS Aqua+Terra", 1),
]

SERVICIOS_EXTRAS = [
    {"nombre": "Perimetros Incendios",
     "url": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Active_Fires/FeatureServer/0/query",
     "tipo": "perimetro_incendio"},
    {"nombre": "Red Flag Warning",
     "url": "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v2/FeatureServer/6/query",
     "tipo": "red_flag_warning"},
    {"nombre": "Fire Weather Watch",
     "url": "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v2/FeatureServer/5/query",
     "tipo": "fire_weather_watch"},
]

def log(msg, level="INFO"):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def descargar_focos():
    log("=" * 50)
    log("CWIA AutoUpdate v3 - identico a NASA FIRMS")
    log("=" * 50)
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
            log(f"  {nombre}: error - {e}", "WARN")
        time.sleep(0.5)
    log(f"Total focos: {len(todos)}")
    return todos

def focos_a_esri(focos):
    features = []
    vistos   = set()
    for f in focos:
        try:
            lat = float(f.get("latitude", 0))
            lon = float(f.get("longitude", 0))
            if not (CO_LAT_MIN <= lat <= CO_LAT_MAX and CO_LON_MIN <= lon <= CO_LON_MAX): continue
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
                    "tipo":        "foco_calor",
                    "actualizado": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                }
            })
        except: continue
    log(f"Focos unicos Colorado: {len(features)}")
    return features

def descargar_servicio(servicio):
    nombre = servicio["nombre"]
    log(f"Descargando {nombre}...")
    try:
        params = {
            "where": "1=1",
            "geometry": f"{CO_LON_MIN},{CO_LAT_MIN},{CO_LON_MAX},{CO_LAT_MAX}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
            "resultRecordCount": 200
        }
        resp = requests.get(servicio["url"], params=params, timeout=30)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
        log(f"  {nombre}: {len(feats)} entidades")
        return feats, servicio["tipo"]
    except Exception as e:
        log(f"  {nombre}: error - {e}", "WARN")
        return [], servicio["tipo"]

def extras_a_esri(features_geo, tipo):
    resultado = []
    for feat in features_geo:
        try:
            geom  = feat.get("geometry", {})
            props = feat.get("properties", {}) or {}
            if not geom: continue
            props["tipo"]        = tipo
            props["estado"]      = "Colorado"
            props["actualizado"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            resultado.append({"geometry": geom, "attributes": props})
        except: continue
    return resultado

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
    if not url: raise RuntimeError("No URL")
    log(f"Servicio: {url}"); return url

def borrar_features(url_svc, token):
    log("Borrando anteriores...")
    resp = requests.post(f"{url_svc}/0/deleteFeatures",
        data={"where": "1=1", "token": token, "f": "json"}, timeout=30)
    resp.raise_for_status()
    log(f"Borrados: {len(resp.json().get('deleteResults', []))}")

def publicar_features(url_svc, token, features):
    if not features: log("Sin features.", "WARN"); return 0
    log(f"Publicando {len(features)} features...")
    total = 0
    for i in range(0, len(features), 200):
        lote = features[i:i+200]
        resp = requests.post(f"{url_svc}/0/addFeatures",
            data={"features": json.dumps(lote), "token": token, "f": "json"}, timeout=60)
        resp.raise_for_status()
        ok = sum(1 for r in resp.json().get("addResults", []) if r.get("success"))
        total += ok; log(f"  Lote {i//200+1}: {ok}/{len(lote)}")
    log(f"Total: {total}"); return total

def main():
    todas = []
    focos    = descargar_focos()
    features = focos_a_esri(focos)
    todas.extend(features)
    log(""); log("Descargando perimetros y alertas...")
    n_extras = 0
    for servicio in SERVICIOS_EXTRAS:
        feats_geo, tipo = descargar_servicio(servicio)
        feats_esri      = extras_a_esri(feats_geo, tipo)
        todas.extend(feats_esri); n_extras += len(feats_esri)
        time.sleep(0.3)
    log(f"TOTAL: {len(todas)} | Focos: {len(features)} | Extras: {n_extras}")
    token   = obtener_token()
    url_svc = obtener_url_servicio(token)
    borrar_features(url_svc, token)
    n = publicar_features(url_svc, token, todas)
    log("=" * 50)
    log(f"COMPLETADO v3 - {n} features en ArcGIS Online")
    log("=" * 50)

if __name__ == "__main__":
    main()
