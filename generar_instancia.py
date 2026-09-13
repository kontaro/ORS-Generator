"""
Generador de instancias sinteticas para el problema de programacion quirurgica
(pabellon x especialidad x medico).

Fuentes publicas en que se basan los supuestos (todas citables, ver README.md):
  - Norma de Listas de Espera 2011 (MINSAL): taxonomia REM-07 de especialidades.
  - IPSUSS (2022), "Como se usan los pabellones quirurgicos en Chile?": stock
    nacional de pabellones y tipologia de hospitales por complejidad.
  - Arancibia-Luna et al. (2026), Rev Med Chile: proporciones nacionales 2024
    de especialistas por especialidad.
  - Meza-Vasquez et al. (CLEI 2025): distribucion empirica de duracion de
    cirugia (media 136.2 min, sd 58.0 min, sobre 78 procedimientos electivos).
  - Literatura de "block scheduling" en programacion de pabellones (Cardoen
    et al. 2010; Guerriero & Guido 2011; Riise, Mannino & Burke 2016): cada
    pabellon se asigna a una sola especialidad por sesion/dia, y los medicos
    trabajan en bloques horarios estandar (dia completo o medio dia AM/PM),
    no en ventanas sueltas - bloques de menos de ~4 horas se consideran
    ineficientes para la operacion del pabellon.

Este generador NO depende de ningun archivo externo: todas las duraciones y
ventanas horarias se generan a partir de distribuciones/parametros descritos
arriba, no de datos hospitalarios privados.
"""

import numpy as np
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Especialidades en alcance (subconjunto de la taxonomia REM-07,
#    restringido a cirugia mayor electiva).
# ---------------------------------------------------------------------------

SPECIALTIES = [
    "Cirugia_Adulto",
    "Traumatologia",
    "Obstetricia",
    "Ginecologia",
    "Oftalmologia",
    "Cirugia_Infantil",
]

# Pesos relativos de especialidad, tanto para la mezcla de pabellones como
# para la dotacion de medicos. Calibrados para ser consistentes con el
# orden de magnitud de las proporciones nacionales 2024 de especialistas
# por especialidad (Arancibia-Luna et al. 2026): Cirugia General y
# Traumatologia y Ortopedia son las especialidades quirurgicas con mayor
# dotacion nacional, seguidas por Obstetricia/Ginecologia, y luego
# Oftalmologia y Cirugia Pediatrica con dotaciones menores. Es un supuesto
# de calibracion (orden de magnitud), no una cifra oficial por hospital.
SPECIALTY_WEIGHTS = {
    "Cirugia_Adulto": 30,
    "Traumatologia": 24,
    "Obstetricia": 18,
    "Ginecologia": 14,
    "Oftalmologia": 9,
    "Cirugia_Infantil": 5,
}

HORIZONTE = (480, 1020)  # 08:00-17:00 en minutos

# Bloques de trabajo estandar para medicos/equipos quirurgicos, siguiendo la
# practica de "block time" descrita en la literatura de gestion de pabellones:
# dia completo o medio dia (AM/PM); bloques mas fragmentados que un medio dia
# se consideran ineficientes y no se modelan aqui.
BLOCK_TYPES = {
    "dia_completo": HORIZONTE,
    "bloque_AM": (HORIZONTE[0], (HORIZONTE[0] + HORIZONTE[1]) // 2),
    "bloque_PM": ((HORIZONTE[0] + HORIZONTE[1]) // 2, HORIZONTE[1]),
}
# Los bloques de dia completo se favorecen levemente (mas eficientes segun la
# literatura de gestion de block time), el resto se reparte entre AM y PM.
BLOCK_TYPE_WEIGHTS = {"dia_completo": 0.35, "bloque_AM": 0.325, "bloque_PM": 0.325}

# Distribucion de duracion de cirugia: Gamma ajustada por metodo de momentos a
# la media (136.2 min) y desviacion estandar (58.0 min) reportadas en
# Meza-Vasquez et al. (CLEI 2025) sobre 78 procedimientos electivos reales.
DURATION_MEAN = 136.2
DURATION_SD = 58.0
_DUR_SHAPE = (DURATION_MEAN / DURATION_SD) ** 2
_DUR_SCALE = (DURATION_SD ** 2) / DURATION_MEAN
DURATION_MIN, DURATION_MAX = 45, 400  # recorte a un rango clinicamente plausible

REALISTIC_SIZE_TIERS = {
    "pequeno (hospital tipo 3/4)": (2, 6),
    "mediano (hospital tipo 2)": (6, 12),
    "grande (hospital tipo 1, alta complejidad)": (12, 20),
}
DEFAULT_INSTANCE_SIZES = [4, 8, 12, 16, 20]


def cargar_datos_cirugias(fuente) -> pd.DataFrame:
    """Carga datos REALES propios de cirugia para reemplazar/complementar la
    distribucion por defecto (calibrada para el sistema chileno). `fuente`
    puede ser un path a .csv/.xlsx, o un DataFrame ya cargado.

    Formato esperado: columnas 'Especialidad' (texto, cualquier nomenclatura)
    y 'Duracion' (minutos, numerico). Una fila por cirugia observada. Ver
    plantilla_datos_propios.csv como ejemplo del formato.
    """
    if isinstance(fuente, pd.DataFrame):
        df = fuente.copy()
    else:
        fuente = Path(fuente)
        df = pd.read_csv(fuente) if fuente.suffix.lower() == ".csv" else pd.read_excel(fuente)
    faltantes = {"Especialidad", "Duracion"} - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas {faltantes} en los datos propios. "
                          f"Se esperan las columnas 'Especialidad' y 'Duracion'.")
    df = df[["Especialidad", "Duracion"]].dropna()
    df["Duracion"] = df["Duracion"].astype(float)
    return df


def pesos_especialidad_desde_datos(datos: pd.DataFrame) -> dict:
    """Deriva pesos de especialidad (para pabellones y medicos) a partir de
    la frecuencia observada en datos propios (ver cargar_datos_cirugias).
    Reemplaza los SPECIALTY_WEIGHTS por defecto por la mezcla real del
    usuario, incluyendo especialidades que no esten en la lista chilena por
    defecto."""
    conteo = datos["Especialidad"].value_counts()
    return conteo.to_dict()


def _muestrear_duraciones(n: int, rng: np.random.Generator, especialidad: str = None,
                           datos_empiricos: pd.DataFrame = None,
                           minimo_bootstrap: int = 5) -> np.ndarray:
    """Si se entregan datos_empiricos con al menos `minimo_bootstrap`
    observaciones para esa especialidad, se remuestrea (bootstrap) desde
    esos datos reales. En caso contrario, se usa la distribucion Gamma por
    defecto calibrada para el sistema chileno (ver README)."""
    if datos_empiricos is not None and especialidad is not None:
        pool = datos_empiricos.loc[datos_empiricos["Especialidad"] == especialidad, "Duracion"].to_numpy()
        if len(pool) >= minimo_bootstrap:
            return rng.choice(pool, size=n, replace=True).astype(int)
    d = rng.gamma(_DUR_SHAPE, _DUR_SCALE, size=n)
    d = np.clip(d, DURATION_MIN, DURATION_MAX)
    return (np.round(d / 5) * 5).astype(int)  # redondeo a multiplos de 5 min


def generar_pabellones(n_pabellones: int, rng: np.random.Generator,
                        pesos_especialidad: dict = SPECIALTY_WEIGHTS) -> pd.DataFrame:
    """Asigna una (y solo una) especialidad a cada pabellon para el dia -
    "block scheduling" / "dedicated OR scheduling policy" (Cardoen et al.
    2010; Guerriero & Guido 2011)."""
    especialidades = list(pesos_especialidad.keys())
    pesos = np.array(list(pesos_especialidad.values()), dtype=float)
    pesos /= pesos.sum()
    asignacion = rng.choice(especialidades, size=n_pabellones, p=pesos)
    disponibilidad = np.full(n_pabellones, HORIZONTE[1] - HORIZONTE[0])
    return pd.DataFrame({
        "Pabellon_ID": range(1, n_pabellones + 1),
        "Especialidad": asignacion,
        "Disponibilidad_min": disponibilidad,
    })


def generar_cirugias(tabla_pabellones: pd.DataFrame, rng: np.random.Generator,
                      factor_sobredemanda: float = 1.5,
                      datos_empiricos: pd.DataFrame = None) -> pd.DataFrame:
    """Genera cirugias candidatas POR ESPECIALIDAD hasta que la duracion total
    candidata alcance factor_sobredemanda veces la capacidad de los pabellones
    de esa especialidad ese dia (para que el problema sea de seleccion real,
    no una asignacion trivial 1 a 1).

    Si se entrega `datos_empiricos` (ver cargar_datos_cirugias), las
    duraciones de cada especialidad se remuestrean desde esos datos reales
    en vez de la distribucion Gamma por defecto."""
    registros = []
    id_counter = 1
    for especialidad, grupo in tabla_pabellones.groupby("Especialidad"):
        capacidad_total = grupo["Disponibilidad_min"].sum()
        objetivo_duracion = factor_sobredemanda * capacidad_total
        duracion_acumulada = 0
        tope_cirugias = 2000
        while duracion_acumulada < objetivo_duracion and id_counter <= tope_cirugias:
            d = int(_muestrear_duraciones(1, rng, especialidad=especialidad,
                                           datos_empiricos=datos_empiricos)[0])
            registros.append({"ID_IQ": id_counter, "Especialidad": especialidad, "Tiempo": d})
            duracion_acumulada += d
            id_counter += 1
    return pd.DataFrame(registros)


def _cobertura_horaria(especialidad: str, tabla_medicos: pd.DataFrame,
                        horizonte: tuple = HORIZONTE) -> float:
    """Fraccion de la jornada cubierta por AL MENOS UN medico de esa
    especialidad (union de intervalos)."""
    medicos_esp = tabla_medicos[tabla_medicos["Especialidad"] == especialidad]
    intervalos = sorted(zip(medicos_esp["Inicio"], medicos_esp["Fin"]))
    fusionados = []
    for s, e in intervalos:
        s, e = max(s, horizonte[0]), min(e, horizonte[1])
        if s >= e:
            continue
        if fusionados and s <= fusionados[-1][1]:
            fusionados[-1] = (fusionados[-1][0], max(fusionados[-1][1], e))
        else:
            fusionados.append((s, e))
    cubierto = sum(e - s for s, e in fusionados)
    return cubierto / (horizonte[1] - horizonte[0])


def _sortear_bloque(rng: np.random.Generator):
    tipos = list(BLOCK_TYPE_WEIGHTS.keys())
    pesos = np.array(list(BLOCK_TYPE_WEIGHTS.values()))
    tipo = rng.choice(tipos, p=pesos / pesos.sum())
    return BLOCK_TYPES[tipo]


def generar_medicos(n_medicos_base: int, tabla_pabellones: pd.DataFrame,
                     rng: np.random.Generator,
                     pesos_especialidad: dict = SPECIALTY_WEIGHTS,
                     cobertura_minima: float = 0.8,
                     max_medicos_extra_por_especialidad: int = 8) -> tuple:
    """Genera el pool base de medicos (cada uno con un bloque estandar:
    dia completo o medio dia AM/PM) y luego, para cada especialidad asignada
    a algun pabellon ese dia, refuerza con medicos adicionales de esa
    especialidad hasta que la cobertura horaria conjunta alcance
    cobertura_minima (o el tope de seguridad)."""
    especialidades_pool = list(pesos_especialidad.keys())
    pesos = np.array(list(pesos_especialidad.values()), dtype=float)
    pesos /= pesos.sum()

    especialidad_medico = list(rng.choice(especialidades_pool, size=n_medicos_base, p=pesos))
    inicio, fin = [], []
    for _ in range(n_medicos_base):
        s, e = _sortear_bloque(rng)
        inicio.append(s)
        fin.append(e)

    especialidades_activas = tabla_pabellones["Especialidad"].unique()
    reporte_cobertura = {}

    for especialidad in especialidades_activas:
        agregados = 0
        while agregados < max_medicos_extra_por_especialidad:
            tabla_tmp = pd.DataFrame({"Especialidad": especialidad_medico, "Inicio": inicio, "Fin": fin})
            cobertura = _cobertura_horaria(especialidad, tabla_tmp)
            if cobertura >= cobertura_minima:
                break
            s, e = _sortear_bloque(rng)
            especialidad_medico.append(especialidad)
            inicio.append(s)
            fin.append(e)
            agregados += 1
        tabla_tmp = pd.DataFrame({"Especialidad": especialidad_medico, "Inicio": inicio, "Fin": fin})
        reporte_cobertura[especialidad] = round(_cobertura_horaria(especialidad, tabla_tmp), 3)

    tabla_medicos = pd.DataFrame({
        "Medico_ID": range(1, len(especialidad_medico) + 1),
        "Especialidad": especialidad_medico,
        "Inicio": inicio,
        "Fin": fin,
    })
    return tabla_medicos, reporte_cobertura


def generar_instancia(n_pabellones: int, seed: int = None,
                       factor_sobredemanda: float = 1.5,
                       medicos_por_pabellon: float = 1.0,
                       cobertura_minima: float = 0.8,
                       max_medicos_extra_por_especialidad: int = 8,
                       pesos_especialidad: dict = None,
                       datos_cirugias_propios=None) -> dict:
    """Si `pesos_especialidad` es None, se usan los pesos por defecto
    (calibrados para Chile, ver README). Si se entrega un dict propio (por
    ejemplo, generado con pesos_especialidad_desde_datos), tanto la mezcla de
    pabellones como el pool de medicos usan esas especialidades y pesos en
    vez de los seis por defecto.

    `datos_cirugias_propios` acepta un DataFrame ya cargado con
    cargar_datos_cirugias, o directamente un path a .csv/.xlsx con columnas
    'Especialidad' y 'Duracion': si se entrega, las duraciones se
    remuestrean desde esos datos reales en vez de la distribucion Gamma
    calibrada para Chile."""
    rng = np.random.default_rng(seed)
    pesos = pesos_especialidad or SPECIALTY_WEIGHTS

    if datos_cirugias_propios is not None and not isinstance(datos_cirugias_propios, pd.DataFrame):
        datos_cirugias_propios = cargar_datos_cirugias(datos_cirugias_propios)

    tabla_pabellones = generar_pabellones(n_pabellones, rng, pesos_especialidad=pesos)
    tabla_cirugias = generar_cirugias(tabla_pabellones, rng, factor_sobredemanda=factor_sobredemanda,
                                       datos_empiricos=datos_cirugias_propios)

    n_medicos_base = max(len(pesos), round(n_pabellones * medicos_por_pabellon))
    tabla_medicos, reporte_cobertura = generar_medicos(
        n_medicos_base, tabla_pabellones, rng, pesos_especialidad=pesos,
        cobertura_minima=cobertura_minima,
        max_medicos_extra_por_especialidad=max_medicos_extra_por_especialidad,
    )

    return {
        "pabellones": tabla_pabellones,
        "cirugias": tabla_cirugias,
        "medicos": tabla_medicos,
        "reporte_cobertura": reporte_cobertura,
    }


def guardar_instancia(instancia: dict, dir_salida: Path, prefijo: str):
    dir_salida.mkdir(parents=True, exist_ok=True)
    instancia["pabellones"].to_excel(dir_salida / f"{prefijo}_Pabellones.xlsx", index=False)
    instancia["cirugias"].to_excel(dir_salida / f"{prefijo}_Cirugias.xlsx", index=False)
    instancia["medicos"].to_excel(dir_salida / f"{prefijo}_Medicos.xlsx", index=False)


if __name__ == "__main__":
    salida = Path("/home/claude/or_instance_gen/instancias")
    for n_pab in DEFAULT_INSTANCE_SIZES:
        inst = generar_instancia(n_pab, seed=42, factor_sobredemanda=1.5)
        guardar_instancia(inst, salida, prefijo=f"{n_pab}_pab")

        cirugias_por_esp = inst["cirugias"].groupby("Especialidad")["Tiempo"].agg(["count", "sum"])
        capacidad_por_esp = inst["pabellones"].groupby("Especialidad")["Disponibilidad_min"].sum()

        print(f"\n--- {n_pab} pabellones ---")
        print("pabellones por especialidad:", inst["pabellones"]["Especialidad"].value_counts().to_dict())
        print(f"cirugias candidatas: {len(inst['cirugias'])}, medicos: {len(inst['medicos'])}")
        for esp in capacidad_por_esp.index:
            dur_cand = cirugias_por_esp.loc[esp, "sum"] if esp in cirugias_por_esp.index else 0
            cap = capacidad_por_esp[esp]
            print(f"  {esp}: demanda/capacidad={dur_cand/cap:.2f}x, "
                  f"cobertura medicos={inst['reporte_cobertura'].get(esp, 0):.2f}")
