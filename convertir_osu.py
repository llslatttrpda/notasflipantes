"""
Convertidor de niveles de osu! al formato de este juego.

Uso:
    python convertir_osu.py "C:\\ruta\\nivel.osz"
    python convertir_osu.py nivel1.osz nivel2.osz --coleccion 2000s
    python convertir_osu.py            (sin argumentos: te pide la ruta del archivo)
    En Windows tambien podes ARRASTRAR el archivo .osz encima de este script.

Que acepta:
    .osz  -> paquete de beatmaps de osu! (el formato normal de los niveles)
    .osk  -> si es un zip que contiene .osu, tambien (ojo: en osu! .osk son SKINS)
    .osu  -> un beatmap suelto (el audio tiene que estar en la misma carpeta)

Solo se convierten beatmaps de osu!mania de 4 teclas (Mode: 3, 4K). Los de otro modo
(standard, taiko, catch) o con otra cantidad de teclas (5K, 7K...) se omiten.
Cada .osu del paquete pasa a ser una DIFICULTAD de la misma cancion.

Resultado:
    canciones/<coleccion>/<artista-titulo>/
        info.json        (titulo, artista, bpm, offset, audio, dificultades)
        <audio>          (el mismo archivo del paquete)
        chart_<dificultad>.txt
    canciones/<coleccion>/coleccion.json   (si no existia)

Notas:
  * El juego tiene un solo BPM por cancion. Se usa el primer timing point. Las notas se
    convierten por TIEMPO real, asi que el chart suena bien aunque la cancion cambie de BPM;
    lo unico es que la grilla del editor no coincide con los cambios de tempo.
  * Las notas que quedan a menos de 3 ms de la grilla del editor (1/16 de beat o tresillos)
    se alinean a ella, para poder editarlas con el mouse. Con --exacto no se toca nada.
  * El mp3 puede necesitar un ajuste fino de sincronizacion: usa las flechas IZQ/DER dentro
    del juego para calibrar el offset.
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import unicodedata
import zipfile

from config import CARRILES

BASE = os.path.dirname(os.path.abspath(__file__))
MODOS = {"0": "osu!standard", "1": "osu!taiko", "2": "osu!catch", "3": "osu!mania"}
HOLD_MIN_BEATS = 0.25      # un LN mas corto que esto se convierte en nota normal
TOLERANCIA_MS = 3.0         # cuanto se puede mover una nota para alinearla a la grilla


# ---------------------------------------------------------------- lectura de .osu
def decodificar(datos):
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("utf-8", errors="ignore")


def parsear_osu(texto):
    secciones, actual = {}, None
    for crudo in texto.splitlines():
        linea = crudo.strip()
        if not linea or linea.startswith("//"):
            continue
        if linea.startswith("[") and linea.endswith("]"):
            actual = linea[1:-1]
            secciones[actual] = []
        elif actual is not None:
            secciones[actual].append(linea)

    def claves(nombre):
        d = {}
        for linea in secciones.get(nombre, []):
            if ":" in linea:
                k, v = linea.split(":", 1)
                d[k.strip()] = v.strip()
        return d

    puntos = []   # (tiempo_ms, ms_por_beat) de los timing points NO heredados
    for linea in secciones.get("TimingPoints", []):
        p = linea.split(",")
        if len(p) < 2:
            continue
        try:
            tiempo, largo = float(p[0]), float(p[1])
        except ValueError:
            continue
        sin_heredar = (p[6].strip() == "1") if len(p) > 6 else largo > 0
        if sin_heredar and largo > 0:
            puntos.append((tiempo, largo))

    objetos = []   # (x, tiempo_ms, tipo, fin_ms o None)
    for linea in secciones.get("HitObjects", []):
        p = linea.split(",")
        if len(p) < 5:
            continue
        try:
            x, t, tipo = int(float(p[0])), int(float(p[2])), int(p[3])
        except ValueError:
            continue
        fin = None
        if tipo & 128 and len(p) > 5:          # hold de mania: "fin:hitSample"
            try:
                fin = int(p[5].split(":")[0])
            except ValueError:
                fin = None
        objetos.append((x, t, tipo, fin))

    return {"general": claves("General"), "meta": claves("Metadata"),
            "dif": claves("Difficulty"), "puntos": puntos, "objetos": objetos}


def notas_mania(mapa):
    """Lista de (tiempo_ms, carril, fin_ms o None) y la cantidad de teclas originales."""
    teclas = max(1, int(float(mapa["dif"].get("CircleSize", 4))))
    notas = []
    for x, t, tipo, fin in mapa["objetos"]:
        col = min(teclas - 1, max(0, x * teclas // 512))
        carril = col   # solo se llega aca con teclas == CARRILES
        es_hold = bool(tipo & 128) and fin is not None and fin > t
        notas.append((t, carril, fin if es_hold else None))
    return teclas, notas


# ---------------------------------------------------------------- utilidades
def slug(texto, defecto="sin-nombre"):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto or defecto


def numero(v):
    return (f"{v:.4f}".rstrip("0").rstrip(".")) or "0"


def cuantizar(beat, ms_beat, exacto):
    """Alinea el beat a la grilla (1/16 o tresillos) si queda a menos de TOLERANCIA_MS."""
    if exacto:
        return round(beat, 4)
    mejor, distancia = beat, TOLERANCIA_MS / ms_beat
    for div in (16, 12):
        q = round(beat * div) / div
        if abs(q - beat) <= distancia:
            mejor, distancia = q, abs(q - beat)
    return round(mejor, 4)


def leer_archivo(ruta):
    """Devuelve ({nombre_en_el_paquete: bytes}, carpeta_base_si_es_suelto)."""
    if ruta.lower().endswith(".osu"):
        carpeta = os.path.dirname(os.path.abspath(ruta))
        contenido = {}
        for nombre in os.listdir(carpeta):
            if nombre == os.path.basename(ruta) or nombre.lower().endswith((".mp3", ".ogg", ".wav")):
                with open(os.path.join(carpeta, nombre), "rb") as f:
                    contenido[nombre] = f.read()
        return contenido
    try:
        with zipfile.ZipFile(ruta) as z:
            return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    except zipfile.BadZipFile:
        raise SystemExit(f"'{ruta}' no es un archivo .osz/.osk valido (no es un zip).")


def parametros_dificultad(rank, total, od):
    """Valores iniciales razonables; se pueden retocar a mano en info.json."""
    velocidad = 400 if total == 1 else round(300 + 220 * rank / (total - 1))
    mult = 1.0 if total == 1 else round(0.8 + 0.7 * rank / (total - 1), 2)
    bueno = min(0.20, max(0.10, round(0.20 - 0.01 * od, 3)))
    perfect = max(0.04, round(bueno * 0.45, 3))
    return velocidad, perfect, bueno, mult


# ---------------------------------------------------------------- conversion
def convertir_archivo(ruta, coleccion, destino, sobrescribir, exacto=False):
    print(f"\n=== {os.path.basename(ruta)} ===")
    contenido = leer_archivo(ruta)
    mapas, descartados = [], []
    for nombre, datos in contenido.items():
        if not nombre.lower().endswith(".osu"):
            continue
        mapa = parsear_osu(decodificar(datos))
        mapa["archivo"] = nombre
        version = mapa["meta"].get("Version", nombre)
        modo = mapa["general"].get("Mode", "0")
        if modo != "3":
            descartados.append((version, MODOS.get(modo, f"modo {modo}"), False))
            continue
        try:
            teclas = int(float(mapa["dif"].get("CircleSize", 4)))
        except ValueError:
            teclas = 0
        if teclas != CARRILES:
            descartados.append((version, f"osu!mania {teclas}K", True))
            continue
        if not mapa["puntos"] or not mapa["objetos"]:
            print(f"  - {nombre}: sin timing points o sin notas, se omite")
            continue
        mapas.append(mapa)

    if descartados:
        cabecera = "Se omitieron" if mapas else "No se convirtio ninguno. Se omitieron"
        print(f"  {cabecera} {len(descartados)} beatmaps (solo se convierte osu!mania de {CARRILES} teclas):")
        for version, motivo, _ in descartados:
            print(f"    - {version}: {motivo}")

    if not mapas:
        if not any(n.lower().endswith(".osu") for n in contenido):
            extra = " Ojo: .osk es el formato de SKINS de osu!; los niveles son .osz." \
                if ruta.lower().endswith(".osk") else ""
            print(f"  No encontre ningun beatmap (.osu) en el archivo.{extra}")
        elif any(not es_mania for _, _, es_mania in descartados):
            print("  Ese nivel es de otro modo de juego. Para este juego busca niveles de osu!mania 4K "
                  "(en la web de osu!, filtro Modo: mania y 4K).")
        return 0

    grupos = {}   # un grupo por archivo de audio (una cancion)
    for m in mapas:
        grupos.setdefault(m["general"].get("AudioFilename", ""), []).append(m)

    creadas = 0
    for audio_nombre, grupo in grupos.items():
        if convertir_cancion(contenido, audio_nombre, grupo, ruta, coleccion, destino, sobrescribir, exacto):
            creadas += 1
    return creadas


def convertir_cancion(contenido, audio_nombre, grupo, ruta_origen, coleccion, destino, sobrescribir, exacto=False):
    meta = grupo[0]["meta"]
    titulo = meta.get("Title") or meta.get("TitleUnicode") or "Sin titulo"
    artista = meta.get("Artist") or meta.get("ArtistUnicode") or ""
    carpeta = os.path.join(destino, coleccion, slug(f"{artista} {titulo}"))
    if os.path.exists(carpeta) and not sobrescribir:
        print(f"  '{carpeta}' ya existe. Usa --sobrescribir para reemplazarla.")
        return False

    # BPM y offset de la cancion: primer timing point del primer beatmap
    ms_beat_orig = grupo[0]["puntos"][0][1]
    bpm = round(60000.0 / ms_beat_orig, 6)
    if abs(bpm - round(bpm, 2)) < 0.0005:      # 101.999999 -> 102
        bpm = round(bpm, 2)
    ms_beat = 60000.0 / bpm                         # con el BPM que va a leer el juego
    offset_ms = grupo[0]["puntos"][0][0]

    convertidos = []
    for m in grupo:
        teclas, notas = notas_mania(m)
        convertidos.append((m, teclas, notas))
    primera = min(t for _, _, notas in convertidos for t, _, _ in notas)
    if primera < offset_ms:   # que ningun beat quede negativo
        offset_ms -= math.ceil((offset_ms - primera) / ms_beat) * ms_beat

    convertidos.sort(key=lambda c: len(c[2]))       # de menos a mas notas = facil -> dificil
    os.makedirs(carpeta, exist_ok=True)

    dificultades, usados = {}, set()
    for rank, (m, teclas, notas) in enumerate(convertidos):
        version = m["meta"].get("Version", f"Dificultad {rank + 1}")
        clave = slug(version, f"dif{rank + 1}")
        while clave in usados:
            clave += "-2"
        usados.add(clave)

        finales = {}
        for t, carril, fin in notas:
            beat = cuantizar((t - offset_ms) / ms_beat, ms_beat, exacto)
            dur = 0.0
            if fin:
                dur = round(cuantizar((fin - offset_ms) / ms_beat, ms_beat, exacto) - beat, 4)
            if dur < HOLD_MIN_BEATS:
                dur = 0.0
            finales[(beat, carril)] = max(dur, finales.get((beat, carril), 0.0))
        nombre_chart = f"chart_{clave}.txt"
        with open(os.path.join(carpeta, nombre_chart), "w") as f:
            f.write(f"# convertido de osu!mania: {version} ({teclas}K) - {len(finales)} notas\n")
            for (beat, carril), dur in sorted(finales.items()):
                f.write(f"{numero(beat)} {carril}" + (f" {numero(dur)}\n" if dur else "\n"))

        od = float(m["dif"].get("OverallDifficulty", 5))
        vel, perfect, bueno, mult = parametros_dificultad(rank, len(convertidos), od)
        dificultades[clave] = {"nombre": version, "chart": nombre_chart, "velocidad": vel,
                               "ventana_perfect": perfect, "ventana_bueno": bueno,
                               "multiplicador": mult}
        largos = sum(1 for d in finales.values() if d)
        print(f"  + {version}: {len(finales)} notas, {largos} largas")

    # audio
    audio_final = ""
    base = os.path.basename(audio_nombre).lower()
    for nombre, datos in contenido.items():
        if os.path.basename(nombre).lower() == base and base:
            audio_final = os.path.basename(nombre)
            with open(os.path.join(carpeta, audio_final), "wb") as f:
                f.write(datos)
            break
    if not audio_final:
        print(f"  ! No encontre el audio '{audio_nombre}' dentro del archivo: copialo a mano a {carpeta}")

    info = {"titulo": titulo, "artista": artista, "bpm": bpm, "offset": round(offset_ms / 1000, 4)}
    if audio_final:
        info["audio"] = audio_final
    info["dificultades"] = dificultades
    with open(os.path.join(carpeta, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

    ruta_col = os.path.join(destino, coleccion, "coleccion.json")
    if not os.path.exists(ruta_col):
        with open(ruta_col, "w", encoding="utf-8") as f:
            json.dump({"titulo": coleccion, "descripcion": "Importadas de osu!"}, f, indent=2, ensure_ascii=False)

    print(f"  -> {carpeta}")
    print(f"     {bpm:g} BPM, offset {info['offset']}s. Si no suena sincronizado, calibra con IZQ/DER.")
    return True


# ---------------------------------------------------------------- programa
def main():
    ap = argparse.ArgumentParser(description="Convierte niveles de osu!mania (.osz/.osk/.osu) a este juego.")
    ap.add_argument("archivos", nargs="*", help="archivos .osz / .osk / .osu")
    ap.add_argument("--coleccion", default="osu", help="coleccion donde se guardan (por defecto: osu)")
    ap.add_argument("--destino", default=os.path.join(BASE, "canciones"), help="carpeta 'canciones' del juego")
    ap.add_argument("--sobrescribir", action="store_true", help="reemplazar canciones ya convertidas")
    ap.add_argument("--exacto", action="store_true", help="no alinear las notas a la grilla del editor")
    args = ap.parse_args()

    archivos = args.archivos
    if not archivos:
        entrada = input("Ruta del archivo .osz/.osk/.osu (se puede arrastrar aca): ").strip().strip('"')
        archivos = [entrada] if entrada else []
    if not archivos:
        print("No indicaste ningun archivo.")
        return 1

    total = 0
    for ruta in archivos:
        if not os.path.isfile(ruta):
            print(f"\nNo existe el archivo: {ruta}")
            continue
        total += convertir_archivo(ruta, args.coleccion, args.destino, args.sobrescribir, args.exacto)
    if total:
        print(f"\nListo: {total} cancion(es) convertida(s). Abri el juego y buscalas en la coleccion '{args.coleccion}'.")
    else:
        print("\nNo se convirtio ninguna cancion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())