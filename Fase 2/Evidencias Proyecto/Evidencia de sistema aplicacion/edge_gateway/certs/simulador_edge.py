import time
import json
import requests
import pandas as pd

LAMBDA_URL = "https://pczeontvrrhrvqjlaluqdvrokm0ysgdo.lambda-url.us-east-1.on.aws/"

def iniciar_simulacion(ruta_csv: str, intervalo_seg: int = 3, max_envios: int = 20):
    print(f"Cargando datos de planta desde: {ruta_csv}")
    df = pd.read_csv(ruta_csv)
    
    # Filtrar solo estados activos para probar los modelos
    df_activo = df[df["ESTADO_operacion"].isin(["Produccion", "Limpieza"])].tail(max_envios)

    for idx, row in df_activo.iterrows():
        payload = {
            "equipo_id": "MOLINO_QLA_01",
            "timestamp": int(time.time()),
            "lectura_actual": row.to_dict()
        }
        
        try:
            inicio = time.time()
            resp = requests.post(LAMBDA_URL, json=payload, timeout=15)
            latencia = round((time.time() - inicio) * 1000, 1)
            
            if resp.status_code == 200:
                data = resp.json()["resultado"]
                diag = data["diagnostico"]["falla"]
                mse = data["vigilancia_autoencoder"]["mse"]
                alerta_ae = data["vigilancia_autoencoder"]["alerta_anomalia_nueva"]
                print(f"[OK {latencia}ms] Estado: {data['estado_operacion']} | Diagnóstico: {diag} | MSE AE: {mse} (Alerta: {alerta_ae})")
            else:
                print(f"[ERROR {resp.status_code}] {resp.text}")
        except Exception as e:
            print(f"[FALLO CONEXIÓN] {e}")
            
        time.sleep(intervalo_seg)

if __name__ == "__main__":
    # Cambia por la ruta a tu CSV de datos de prueba o usa test_payload.json en bucle
    with open("../lambda_inferencia/app/test_payload.json", "r") as f:
        muestra = json.load(f)
    
    print("Enviando telemetría desde Edge Gateway hacia AWS Lambda...")
    for i in range(5):
        muestra["timestamp"] = int(time.time())
        r = requests.post(LAMBDA_URL, json=muestra)
        print(f"Envío #{i+1} -> Status {r.status_code} | Diagnóstico: {r.json()['resultado']['diagnostico']['falla']}")
        time.sleep(2)