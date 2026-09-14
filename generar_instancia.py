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

import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

GENERATOR_VERSION = "1.2"

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

    # 'Tiempo' se acepta como alias de 'Duracion' (es el nombre que usa la
    # tabla de cirugias que produce este mismo generador, y con el que
    # muchos registros hospitalarios ya vienen etiquetados).
    if "Duracion" not in df.columns and "Tiempo" in df.columns:
        df = df.rename(columns={"Tiempo": "Duracion"})

    faltantes = {"Especialidad", "Duracion"} - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas {faltantes} en los datos propios. "
                          f"Se esperan las columnas 'Especialidad' y 'Duracion' "
                          f"('Tiempo' tambien se acepta como nombre de la columna de duracion).")
    df = df[["Especialidad", "Duracion"]].dropna()
    df["Especialidad"] = df["Especialidad"].astype(str)
    df["Duracion"] = df["Duracion"].astype(float)
    return df


def pesos_especialidad_desde_datos(datos: pd.DataFrame) -> dict:
    """Deriva pesos de especialidad (para pabellones y medicos) a partir de
    la frecuencia observada en datos propios (ver cargar_datos_cirugias).
    Reemplaza los SPECIALTY_WEIGHTS por defecto por la mezcla real del
    usuario, incluyendo especialidades que no esten en la lista chilena por
    defecto."""
    conteo = datos["Especialidad"].value_counts()
    return {str(k): int(v) for k, v in conteo.items()}


def _ajustar_gamma_por_especialidad(datos_empiricos: pd.DataFrame, especialidad: str,
                                     minimo_ajuste: int = 5) -> tuple:
    """Ajusta (por metodo de momentos, igual que el ajuste global chileno) una
    Gamma a la media y desviacion estandar OBSERVADAS de esa especialidad en
    datos_empiricos - es decir, adapta la forma de la Gamma a la variabilidad
    real de ESA especialidad, en vez de reusar los parametros globales
    (DURATION_MEAN/DURATION_SD, calibrados sobre el conjunto de 78
    procedimientos de Meza-Vasquez et al., mezclando todas las especialidades).
    Si hay menos de `minimo_ajuste` observaciones, o la desviacion estandar
    observada es 0 (todas las cirugias de esa especialidad duran lo mismo),
    se cae a los parametros globales por defecto."""
    pool = datos_empiricos.loc[datos_empiricos["Especialidad"] == especialidad, "Duracion"].to_numpy()
    if len(pool) >= minimo_ajuste:
        media, sd = pool.mean(), pool.std(ddof=0)
        if sd > 0:
            return (media / sd) ** 2, (sd ** 2) / media
    return _DUR_SHAPE, _DUR_SCALE


def _muestrear_duraciones(n: int, rng: np.random.Generator, especialidad: str = None,
                           datos_empiricos: pd.DataFrame = None,
                           minimo_bootstrap: int = 5,
                           modo_duracion_propia: str = "auto",
                           prop_gamma_en_mixto: float = 0.5) -> np.ndarray:
    """Genera `n` duraciones para `especialidad`. Si no hay `datos_empiricos`
    (o no hay ninguna observacion de esa especialidad en ellos), siempre usa
    la Gamma global calibrada para Chile. Si SI hay observaciones propias
    para esa especialidad, el comportamiento depende de `modo_duracion_propia`:

      - "bootstrap" (Opcion 1: "los tiempos que estan"): remuestrea SIEMPRE
        con reemplazo desde las duraciones observadas para esa especialidad,
        sin importar cuantas observaciones haya (mientras haya al menos una).
        Nunca inventa una duracion que no este en los datos.
      - "bootstrap_gamma" (Opcion 2: "los tiempos que estan" + variacion
        gamma): cada cirugia generada tiene probabilidad
        `prop_gamma_en_mixto` de salir de una Gamma ajustada a la media/sd
        PROPIA de esa especialidad (ver _ajustar_gamma_por_especialidad,
        redondeada al multiplo de 5 mas cercano), y probabilidad
        `1 - prop_gamma_en_mixto` de salir del bootstrap de los datos reales
        (como en el modo "bootstrap"). Esto agrega variabilidad continua
        alrededor de la distribucion observada, en vez de limitarse a repetir
        exactamente los valores ya vistos.
      - "auto" (compatibilidad hacia atras): bootstrap si hay al menos
        `minimo_bootstrap` observaciones para esa especialidad; si no, Gamma
        global (comportamiento original, previo a estos dos modos).

    Si el modo pide bootstrap pero la especialidad no tiene NINGUNA
    observacion propia, se avisa con un warning y se usa la Gamma global para
    esa especialidad puntual (no puede haber bootstrap sin datos)."""
    pool = None
    if datos_empiricos is not None and especialidad is not None:
        pool = datos_empiricos.loc[datos_empiricos["Especialidad"] == especialidad, "Duracion"].to_numpy()
        if len(pool) == 0:
            pool = None

    if pool is not None:
        if modo_duracion_propia == "bootstrap":
            return rng.choice(pool, size=n, replace=True).astype(int)

        if modo_duracion_propia == "bootstrap_gamma":
            es_gamma = rng.random(n) < prop_gamma_en_mixto
            salida = rng.choice(pool, size=n, replace=True).astype(float)
            n_gamma = int(es_gamma.sum())
            if n_gamma > 0:
                shape, scale = _ajustar_gamma_por_especialidad(datos_empiricos, especialidad)
                d = rng.gamma(shape, scale, size=n_gamma)
                d = np.clip(d, DURATION_MIN, DURATION_MAX)
                salida[es_gamma] = np.round(d / 5) * 5
            return salida.astype(int)

        if modo_duracion_propia == "auto" and len(pool) >= minimo_bootstrap:
            return rng.choice(pool, size=n, replace=True).astype(int)

    elif datos_empiricos is not None and especialidad is not None \
            and modo_duracion_propia in ("bootstrap", "bootstrap_gamma"):
        warnings.warn(
            f"La especialidad '{especialidad}' no tiene ninguna observacion en "
            "datos_cirugias_propios; no se puede generar duraciones con "
            f"modo_duracion_propia='{modo_duracion_propia}' para ella. Se usa "
            "la Gamma global por defecto solo para esta especialidad.",
            UserWarning, stacklevel=2,
        )

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
                      datos_empiricos: pd.DataFrame = None,
                      modo_duracion_propia: str = "auto",
                      prop_gamma_en_mixto: float = 0.5) -> pd.DataFrame:
    """Genera cirugias candidatas POR ESPECIALIDAD hasta que la duracion total
    candidata alcance factor_sobredemanda veces la capacidad de los pabellones
    de esa especialidad ese dia (para que el problema sea de seleccion real,
    no una asignacion trivial 1 a 1).

    Si se entrega `datos_empiricos` (ver cargar_datos_cirugias), las
    duraciones de cada especialidad se generan segun `modo_duracion_propia`
    (ver _muestrear_duraciones): "bootstrap" (solo los tiempos observados),
    "bootstrap_gamma" (tiempos observados + variacion gamma propia de la
    especialidad, mezclados segun `prop_gamma_en_mixto`), o "auto"
    (comportamiento original: bootstrap si hay >= 5 observaciones, si no
    Gamma global)."""
    registros = []
    id_counter = 1
    for especialidad, grupo in tabla_pabellones.groupby("Especialidad"):
        capacidad_total = grupo["Disponibilidad_min"].sum()
        objetivo_duracion = factor_sobredemanda * capacidad_total
        duracion_acumulada = 0
        tope_cirugias = 2000
        while duracion_acumulada < objetivo_duracion and id_counter <= tope_cirugias:
            d = int(_muestrear_duraciones(1, rng, especialidad=especialidad,
                                           datos_empiricos=datos_empiricos,
                                           modo_duracion_propia=modo_duracion_propia,
                                           prop_gamma_en_mixto=prop_gamma_en_mixto)[0])
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


def generar_medicos(tabla_pabellones: pd.DataFrame, rng: np.random.Generator,
                     medicos_por_pabellon: float = 1.0,
                     cobertura_minima: float = 0.8,
                     max_medicos_extra_por_especialidad: int = 8) -> tuple:
    """Para CADA especialidad con al menos un pabellon asignado ese dia, la
    base de medicos de esa especialidad es
    ceil(medicos_por_pabellon * n_pabellones_de_esa_especialidad) - al menos
    un medico por pabellon de esa especialidad (con medicos_por_pabellon=1.0,
    el default), para que en principio cada pabellon de esa especialidad
    pueda operar en paralelo con su propio equipo (ver Fei, Meskens & Chu
    2006 sobre "block scheduling": un cirujano por pabellon por dia).

    Esto reemplaza un diseño anterior en el que la cantidad TOTAL de medicos
    se repartia por un sorteo ponderado por especialidad, INDEPENDIENTE del
    sorteo de especialidad de los pabellones: por azar, una especialidad
    podia terminar con varios pabellones activos pero muy pocos medicos (o
    viceversa), y la metrica de cobertura horaria (que solo mide UNION de
    horarios, no capacidad simultanea) no lo detectaba - un pabellon
    "cubierto" el 100% del dia por 2 medicos igual no alcanza para operar
    4 pabellones de esa especialidad en paralelo.

    Sobre esa base por pabellon, se sigue reforzando por especialidad (hasta
    max_medicos_extra_por_especialidad) hasta alcanzar cobertura_minima
    (fraccion del dia cubierta por AL MENOS UN medico) - esto ahora cierra
    huecos de horario (p.ej. si por azar todos los medicos base de una
    especialidad salieron con bloque AM), no huecos de dotacion."""
    especialidades_activas = tabla_pabellones["Especialidad"].value_counts()

    especialidad_medico, inicio, fin = [], [], []
    for especialidad, n_pabellones_esp in especialidades_activas.items():
        n_base_esp = max(1, int(np.ceil(medicos_por_pabellon * n_pabellones_esp)))
        for _ in range(n_base_esp):
            s, e = _sortear_bloque(rng)
            especialidad_medico.append(especialidad)
            inicio.append(s)
            fin.append(e)

    reporte_cobertura = {}

    for especialidad in especialidades_activas.index:
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
                       datos_cirugias_propios=None,
                       usar_mezcla_de_datos_propios: bool = True,
                       modo_duracion_propia: str = "bootstrap",
                       prop_gamma_en_mixto: float = 0.5) -> dict:
    """Si `pesos_especialidad` es None, se usan los pesos por defecto
    (calibrados para Chile, ver README) - A MENOS que se entregue
    `datos_cirugias_propios`, en cuyo caso (por defecto,
    usar_mezcla_de_datos_propios=True) los pesos se derivan automaticamente
    de la frecuencia observada en esos datos (equivalente a llamar
    pesos_especialidad_desde_datos). Esto es porque la lista de cirugias que
    alguien entrega ya es, en si misma, la distribucion a priori que tiene
    esa persona/hospital: si no se dice lo contrario, se asume que esa es la
    mezcla que se quiere reproducir. Pasa usar_mezcla_de_datos_propios=False
    para mantener la mezcla chilena por defecto aunque se entreguen datos
    propios.

    Si se entrega un `pesos_especialidad` EXPLICITO (propio o por defecto)
    junto con `datos_cirugias_propios` -por ejemplo, para fijar una mezcla
    objetivo distinta a la mezcla observada en los datos-, ambos deben usar
    las mismas etiquetas de especialidad para que el bootstrap de duraciones
    funcione: si ninguna especialidad de `pesos_especialidad` tiene
    observaciones en `datos_cirugias_propios`, se emite un warning (en vez de
    caer en silencio a la Gamma por defecto para todas las especialidades).

    `datos_cirugias_propios` acepta un DataFrame ya cargado con
    cargar_datos_cirugias, o directamente un path a .csv/.xlsx con columnas
    'Especialidad' y 'Duracion' (o 'Tiempo'). Cuando se entrega, cada
    especialidad puede tener cirugias de distintos tiempos, y esa
    distribucion propia (dada por la lista de cirugias) se usa segun
    `modo_duracion_propia`:

      - "bootstrap" (default, Opcion 1): las cirugias generadas usan
        exclusivamente los tiempos que estan en tus datos para esa
        especialidad (remuestreo con reemplazo). Nunca inventa una duracion
        fuera de lo observado.
      - "bootstrap_gamma" (Opcion 2): ademas de generar cirugias con los
        tiempos que estan, agrega cirugias con duraciones muestreadas de una
        Gamma ajustada a la media/sd PROPIA de esa especialidad (no la Gamma
        global chilena), redondeadas al multiplo de 5 mas cercano. La
        fraccion de cirugias que sale de la Gamma en vez del bootstrap la
        fija `prop_gamma_en_mixto` (0.5 = mitad y mitad).

    En ambos modos, si una especialidad no tiene ninguna observacion propia
    (p.ej. porque diste un `pesos_especialidad` con etiquetas que no calzan
    con tus datos), se avisa con un warning y esa especialidad puntual usa la
    Gamma global chilena. Pasa `modo_duracion_propia="auto"` para el
    comportamiento previo a estos dos modos (bootstrap solo si hay >= 5
    observaciones, si no Gamma global).

    Reproducibilidad
    -----------------
    Si `seed` es None, NO se deja la generacion sin semilla: se sortea una
    semilla concreta (con entropia del sistema) y se usa esa, para que la
    instancia siga siendo reproducible aunque no hayas fijado un seed a
    mano. La semilla efectivamente usada (junto con el resto de los
    parametros y, si corresponde, la mezcla de especialidades ya resuelta)
    queda en `instancia["metadata"]`, y `guardar_instancia` la escribe en un
    .json junto a los .xlsx. Usa `regenerar_desde_metadata` para reconstruir
    exactamente la misma instancia a partir de ese .json."""
    if seed is None:
        seed = int(np.random.default_rng().integers(0, 2**31 - 1))
    rng = np.random.default_rng(seed)

    datos_cirugias_propios_arg = datos_cirugias_propios

    if datos_cirugias_propios is not None and not isinstance(datos_cirugias_propios, pd.DataFrame):
        datos_cirugias_propios = cargar_datos_cirugias(datos_cirugias_propios)

    if pesos_especialidad is not None:
        pesos = pesos_especialidad
        if datos_cirugias_propios is not None:
            especialidades_datos = set(datos_cirugias_propios["Especialidad"].unique())
            if not (set(pesos.keys()) & especialidades_datos):
                warnings.warn(
                    "Ninguna especialidad de 'pesos_especialidad' "
                    f"({sorted(pesos.keys())}) aparece en 'datos_cirugias_propios' "
                    f"(etiquetas presentes: {sorted(especialidades_datos)}). El "
                    "bootstrap de duraciones no encontrara observaciones para "
                    "ninguna especialidad y usara la distribucion Gamma por "
                    "defecto para todas, ignorando los datos reales. Revisa que "
                    "las etiquetas coincidan, o deja pesos_especialidad=None para "
                    "derivar los pesos automaticamente desde tus datos.",
                    UserWarning, stacklevel=2,
                )
    elif datos_cirugias_propios is not None and usar_mezcla_de_datos_propios:
        pesos = pesos_especialidad_desde_datos(datos_cirugias_propios)
    else:
        pesos = SPECIALTY_WEIGHTS

    tabla_pabellones = generar_pabellones(n_pabellones, rng, pesos_especialidad=pesos)
    tabla_cirugias = generar_cirugias(tabla_pabellones, rng, factor_sobredemanda=factor_sobredemanda,
                                       datos_empiricos=datos_cirugias_propios,
                                       modo_duracion_propia=modo_duracion_propia,
                                       prop_gamma_en_mixto=prop_gamma_en_mixto)

    tabla_medicos, reporte_cobertura = generar_medicos(
        tabla_pabellones, rng, medicos_por_pabellon=medicos_por_pabellon,
        cobertura_minima=cobertura_minima,
        max_medicos_extra_por_especialidad=max_medicos_extra_por_especialidad,
    )

    if isinstance(datos_cirugias_propios_arg, pd.DataFrame):
        descripcion_datos_propios = (
            f"<DataFrame en memoria: {len(datos_cirugias_propios_arg)} filas, "
            f"especialidades: {sorted(datos_cirugias_propios_arg['Especialidad'].unique())}> "
            "(no se guardan los tiempos crudos en la metadata; para regenerar "
            "esta instancia hay que volver a pasar el mismo DataFrame a mano)"
        )
    elif datos_cirugias_propios_arg is not None:
        descripcion_datos_propios = str(datos_cirugias_propios_arg)
    else:
        descripcion_datos_propios = None

    metadata = {
        "generador_version": GENERATOR_VERSION,
        "n_pabellones": n_pabellones,
        "seed": seed,
        "factor_sobredemanda": factor_sobredemanda,
        "medicos_por_pabellon": medicos_por_pabellon,
        "cobertura_minima": cobertura_minima,
        "max_medicos_extra_por_especialidad": max_medicos_extra_por_especialidad,
        "pesos_especialidad": pesos,
        "datos_cirugias_propios": descripcion_datos_propios,
        "usar_mezcla_de_datos_propios": usar_mezcla_de_datos_propios,
        "modo_duracion_propia": modo_duracion_propia,
        "prop_gamma_en_mixto": prop_gamma_en_mixto,
    }

    return {
        "pabellones": tabla_pabellones,
        "cirugias": tabla_cirugias,
        "medicos": tabla_medicos,
        "reporte_cobertura": reporte_cobertura,
        "metadata": metadata,
    }


def guardar_instancia(instancia: dict, dir_salida: Path, prefijo: str):
    dir_salida.mkdir(parents=True, exist_ok=True)
    instancia["pabellones"].to_excel(dir_salida / f"{prefijo}_Pabellones.xlsx", index=False)
    instancia["cirugias"].to_excel(dir_salida / f"{prefijo}_Cirugias.xlsx", index=False)
    instancia["medicos"].to_excel(dir_salida / f"{prefijo}_Medicos.xlsx", index=False)
    if "metadata" in instancia:
        ruta_metadata = dir_salida / f"{prefijo}_metadata.json"
        with open(ruta_metadata, "w", encoding="utf-8") as f:
            json.dump(instancia["metadata"], f, ensure_ascii=False, indent=2)


def regenerar_desde_metadata(ruta_metadata) -> dict:
    """Reconstruye exactamente la misma instancia (mismo seed y mismos
    parametros) a partir del `{prefijo}_metadata.json` que guarda
    guardar_instancia.

    Si la instancia original recibio `datos_cirugias_propios` como un
    DataFrame ya cargado en memoria (no como un path a archivo), la
    metadata no guarda los tiempos crudos -para no terminar reintroduciendo
    datos privados en un artefacto versionable como este .json-, solo un
    resumen. En ese caso hay que volver a pasar esos mismos datos a mano via
    el argumento `datos_cirugias_propios_override`."""
    ruta_metadata = Path(ruta_metadata)
    with open(ruta_metadata, "r", encoding="utf-8") as f:
        meta = json.load(f)

    datos_propios = meta.get("datos_cirugias_propios")
    if isinstance(datos_propios, str) and datos_propios.startswith("<DataFrame en memoria"):
        raise ValueError(
            "Esta instancia se genero con datos_cirugias_propios entregados "
            "como un DataFrame en memoria, y la metadata no guarda los datos "
            "crudos. Vuelve a generarla llamando a generar_instancia(...) "
            "directamente, pasando el mismo DataFrame junto con estos "
            f"parametros: {meta}"
        )

    return generar_instancia(
        n_pabellones=meta["n_pabellones"],
        seed=meta["seed"],
        factor_sobredemanda=meta["factor_sobredemanda"],
        medicos_por_pabellon=meta["medicos_por_pabellon"],
        cobertura_minima=meta["cobertura_minima"],
        max_medicos_extra_por_especialidad=meta["max_medicos_extra_por_especialidad"],
        pesos_especialidad=meta["pesos_especialidad"],
        datos_cirugias_propios=datos_propios,
        modo_duracion_propia=meta["modo_duracion_propia"],
        prop_gamma_en_mixto=meta["prop_gamma_en_mixto"],
    )


if __name__ == "__main__":
    salida = Path("/home/claude/or_instance_gen/instancias")
    for n_pab in DEFAULT_INSTANCE_SIZES:
        inst = generar_instancia(n_pab, seed=42, factor_sobredemanda=1.5)
        guardar_instancia(inst, salida, prefijo=f"{n_pab}_pab")

        cirugias_por_esp = inst["cirugias"].groupby("Especialidad")["Tiempo"].agg(["count", "sum"])
        capacidad_por_esp = inst["pabellones"].groupby("Especialidad")["Disponibilidad_min"].sum()

        print(f"\n--- {n_pab} pabellones (seed={inst['metadata']['seed']}) ---")
        print("pabellones por especialidad:", inst["pabellones"]["Especialidad"].value_counts().to_dict())
        print(f"cirugias candidatas: {len(inst['cirugias'])}, medicos: {len(inst['medicos'])}")
        for esp in capacidad_por_esp.index:
            dur_cand = cirugias_por_esp.loc[esp, "sum"] if esp in cirugias_por_esp.index else 0
            cap = capacidad_por_esp[esp]
            print(f"  {esp}: demanda/capacidad={dur_cand/cap:.2f}x, "
                  f"cobertura medicos={inst['reporte_cobertura'].get(esp, 0):.2f}")
