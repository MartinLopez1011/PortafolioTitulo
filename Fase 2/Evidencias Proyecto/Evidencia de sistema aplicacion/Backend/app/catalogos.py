"""Catálogos compartidos entre rutas y simulador (evita importaciones circulares)."""

# Punto de mantención de cada modo de falla. 'clave' es el nombre que usa el modelo predictivo en la
# bitácora (estado_equipos.json) y 'equipo' el texto que se muestra. Las intervenciones de cada uno se
# obtienen de mantenimiento_fallas (correctivas, preventivas y predictivas que atendieron esa falla).
EQUIPOS = [
    {"clave": "filtro", "equipo": "F-101 filtro de línea", "componente": "F-101", "falla": "Filtro_Obstruido"},
    {"clave": "radar", "equipo": "TK-101 radar de nivel", "componente": "TK-101",
     "falla": "Advertencia_Radar_Sucio_Betun"},
    {"clave": "caldera", "equipo": "TK-101 caldera / calefactor de betún", "componente": "TK-101",
     "falla": "Sobrecarga_Motor_Por_Asfalto_Frio"},
    {"clave": "intercambiador", "equipo": "E-301 intercambiador de calor", "componente": "E-301",
     "falla": "Ensuciamiento_Intercambiador"},
    {"clave": "caudalimetro", "equipo": "FT-201 caudalímetro solución", "componente": "FT-201",
     "falla": "Cortocircuito_Transmisor_Caudal_Sol"},
    {"clave": "pt100", "equipo": "TT-101 Pt100 betún", "componente": "TT-101",
     "falla": "Falla_Electrica_PT100_Betun"},
    {"clave": "rodamientos", "equipo": "MC-01 rodamientos del molino", "componente": "MC-01",
     "falla": "Desgaste_Rodamientos_Molino"},
]

SQL_INTERVENCIONES = """
               FROM mantpred.mantenimientos m
               JOIN mantpred.mantenimiento_fallas mf ON mf.mantenimiento_id = m.id
               JOIN mantpred.tipos_falla tf ON tf.id = mf.tipo_falla_id
               WHERE m.equipo_id = %s AND m.fuente = %s
                 AND (m.fecha_inicio <= %s OR m.origen_registro = 'dashboard')
                 AND tf.codigo = %s"""
