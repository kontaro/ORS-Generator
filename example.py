from generar_instancia import generar_instancia, guardar_instancia
from pathlib import Path

instancia1 = generar_instancia(n_pabellones=12, seed=42, factor_sobredemanda=1.5)
instancia2 = generar_instancia(n_pabellones=14, seed=42, factor_sobredemanda=1.5)
instancia3 = generar_instancia(n_pabellones=16, seed=42, factor_sobredemanda=1.5)
instancia4 = generar_instancia(n_pabellones=18, seed=42, factor_sobredemanda=1.5)
instancia5 = generar_instancia(n_pabellones=20, seed=42, factor_sobredemanda=1.5)
guardar_instancia(instancia1, Path("instancias"), prefijo="12_pab")
guardar_instancia(instancia2, Path("instancias"), prefijo="14_pab")
guardar_instancia(instancia3, Path("instancias"), prefijo="16_pab")
guardar_instancia(instancia4, Path("instancias"), prefijo="18_pab")
guardar_instancia(instancia5, Path("instancias"), prefijo="20_pab")

print(instancia1["reporte_cobertura"])  # coverage fraction per active specialty