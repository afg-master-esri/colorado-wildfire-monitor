import requests, json, datetime, os, time

NASA_API_KEY  = os.environ["NASA_FIRMS_API_KEY"]
AGOL_USERNAME = os.environ["AGOL_USERNAME"]
AGOL_PASSWORD = os.environ["AGOL_PASSWORD"]
AGOL_LAYER_ID = os.environ["AGOL_LAYER_ID"]

CO_BBOX = "-109.060253,36.992426,-102.041524,41.003444"
FIRMS_SOURCES = [
    ("VIIRS_SNPP_NRT",    "VIIRS S-NPP"),
    ("VIIRS_NOAA20_NRT",  "VIIRS NOAA-20"),
    ("MODIS_NRT",         "MODIS Aqua & Terra"),
]

SERVICIOS_POLIGONOS = [
    {
        "nombre": "Perimetros Incendios Activos",
        "url": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Active_Fires/FeatureServer/0/query",
        "tipo": "perimetro"
    },
    {
        "nombre": "Alertas Red Flag Warning",
        "url": "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v2/FeatureServer/6/query",
        "tipo": "alerta_red_flag"
    },
    {
        "nombre": "Fire Weather Watch",
        "url": "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v2/FeatureServer/5/query",
        "tipo": "fire_weather_watch"
    },
]

def log(msg, level="INFO"):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def descargar_focos():
    log("Descargando focos NASA FIRMS - Colorado...")
    todos = []
    for source, nombre in FIRMS_SOURCES:
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
               f"{NASA_API_KEY}/{source}/{CO_BBOX}/1")
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
            log(f"  {nombre}: {len(todos)-n} detecciones")
        except Exception as e:
            log(f"  {nombre}: error - {e}", "WARN")
        time.sleep(0.5)
    log(f"Total focos: {len(todos)}")
    return todos

def focos_a_esri(focos):
    features = []
    for f in focos:
        try:
            lat = float(f.get("latitude", 0))
            lon = float(f.get("longitude", 0))
            if not (36.99 <= lat <= 41.01 and -109.07 <= lon <= -102.04): continue
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
    log(f"Focos en Colorado: {len(features)}")
    return features

def descargar_poligonos_colorado(servicio):
    nombre = servicio["nombre"]
    log(f"Descargando {nombre}...")
    try:
        params = {
            "where":         "1=1",
            "geometry":      "-109.07,36.99,-102.04,41.01",
            "geometryType":  "esriGeometryEnvelope",
            "spatialRel":    "esriSpatialRelIntersects",
            "outFields":     "*",
            "returnGeometry":"true",
            "f":             "geojson",
            "resultRecordCount": 100
        }
        resp = requests.get(servicio["url"], params=params, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        log(f"  {nombre}: {len(features)} entidades en Colorado")
        return features, servicio["tipo"]
    except Exception as e:
        log(f"  {nombre}: error - {e}", "WARN")
