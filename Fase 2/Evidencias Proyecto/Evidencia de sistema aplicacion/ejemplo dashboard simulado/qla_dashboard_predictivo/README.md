# Química Latinoamericana: mantenimiento predictivo del molino coloidal MC-01

Dashboard que simula la operación de un año completo e integra todos los modelos:

| Componente | Qué hace | Archivo que necesita |
|---|---|---|
| Reglas fijas | Fallas de instrumento y límites de proceso | (en `config.py`) |
| Identificación | Qué falla está ocurriendo ahora (LightGBM jerárquico) | `config_modelo.joblib` |
| Autoencoder | Anomalías, fallas raras o desconocidas, índice de salud | `autoencoder_molino_QLA.keras` y `autoencoder_molino_config.joblib` |
| Predicción | Riesgo de falla a 24 h, 5 días y 15 días | `modelo_predictivo.joblib` |
| Datos | Año de operación y bitácora | `Dataset_Molino_QLA_Realista.zip` y `Bitacora_Mantenimiento_QLA.csv` |

Los archivos de modelos salen de las descargas de los notebooks (descomprime cada `.zip` en esta carpeta).
Si falta algún modelo, el dashboard funciona con los que estén disponibles.

## Ejecutar

```
python -m venv venv
venv\Scripts\activate            (Windows)   |   source venv/bin/activate   (Linux/Mac)
pip install -r requirements.txt
uvicorn app:app --reload
```

Abre http://127.0.0.1:8000. Usa las mismas versiones de scikit-learn, LightGBM y TensorFlow que en Colab.

## Cómo simular el paso de reactivo a predictivo

1. La simulación parte el 1 de septiembre de 2026 (periodo que ningún modelo vio). Con "Ir a" puedes saltar a cualquier mes o a 3 días antes de una falla real.
2. En **Simulación de fallas**, inyecta una falla gradual (por ejemplo, "Filtro obstruyéndose") y sube la velocidad.
3. En **Predicción**, observa cómo el riesgo sube a 15 días, luego a 5 días y a 24 horas, antes de que la falla aparezca en Proceso.
4. Presiona **Registrar intervención** en el equipo en riesgo: se registra en la bitácora, se reinicia el desgaste acumulado y la falla simulada queda corregida.
5. En **Mantenimiento** verás el porcentaje de mantenimiento planificado y el MTBF por equipo.

## Estructura

```
app.py           servidor y ciclo de simulación
config.py        sensores, fallas, reglas, indicadores
modelos.py       identificación y autoencoder
predictivo.py    variables horarias y predicción (igual que el notebook)
fuentes.py       reproducción del año e inyección de fallas
registro.py      base SQLite: lecturas, alarmas, intervenciones
escenarios.py    fallas simuladas predefinidas y personalizadas
static/          interfaz (HTML, CSS, JS, logo)
```
