"""Convierte charts de Clone Hero (.chart o .mid) al formato de este juego.

Uso:
    python convertir_chart.py "Cancion.chart"
    python convertir_chart.py "notes.mid" --dificultad Hard --instrumento DoubleBass

Escribe un chart.txt en la misma carpeta del archivo (o donde diga --salida).
Los charts se bajan de https://www.enchor.us
"""
import argparse
import os
import re

DIFICULTADES = ["Easy", "Medium", "Hard", "Expert"]
INSTRUMENTOS = ["Single", "DoubleBass", "DoubleGuitar", "Keyboard", "Drums"]


def seccion(texto, nombre):
    m = re.search(r"\[" + re.escape(nombre) + r"\]\s*\{(.*?)\}", texto, re.S)
    return m.group(1) if m else None


def mapa_tempos(texto):
    cuerpo = seccion(texto, "SyncTrack") or ""
    tempos = sorted((int(m.group(1)), int(m.group(2)) / 1000)
                    for m in re.finditer(r"(\d+)\s*=\s*B\s+(\d+)", cuerpo))
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, tempos[0][1] if tempos else 120.0))
    return tempos


def segundos(tick, tempos, res):
    """Tiempo real en segundos de un tick, siguiendo los cambios de tempo."""
    seg = 0.0
    for i, (t0, bpm) in enumerate(tempos):
        t1 = tempos[i + 1][0] if i + 1 < len(tempos) else None
        if t1 is None or tick < t1:
            return seg + (tick - t0) / res * 60 / bpm
        seg += (t1 - t0) / res * 60 / bpm
    return seg


PISTAS_MID = {"Single": "PART GUITAR", "DoubleBass": "PART BASS", "Keyboard": "PART KEYS"}
BASE_MID = {"Easy": 60, "Medium": 72, "Hard": 84, "Expert": 96}


def leer_chart(ruta, dif, inst):
    """Devuelve (resolucion, tempos, notas) con notas = [(tick, carril, largo_en_ticks)]."""
    with open(ruta, encoding="utf-8", errors="ignore") as f:
        texto = f.read()
    song = seccion(texto, "Song") or ""
    m = re.search(r"Resolution\s*=\s*(\d+)", song)
    res = int(m.group(1)) if m else 192
    cuerpo = seccion(texto, f"{dif}{inst}")
    if cuerpo is None:
        hay = re.findall(r"\[([A-Za-z]+)\]", texto)
        raise SystemExit(f"No encontre la seccion [{dif}{inst}] en el archivo. "
                         f"Hay: {', '.join(hay)}")
    notas = []
    for linea in cuerpo.splitlines():
        tick, _, resto = linea.strip().partition("=")
        resto = resto.split()
        if len(resto) > 1 and resto[0] == "N" and resto[1] in "01234":
            notas.append((int(tick), int(resto[1]), int(resto[2]) if len(resto) > 2 else 0))
    return res, mapa_tempos(texto), notas


def leer_mid(ruta, dif, inst):
    """Lee un .mid de Clone Hero/Guitar Hero sin librerias externas."""
    if inst not in PISTAS_MID:
        raise SystemExit(f"Para .mid solo se soporta: {', '.join(PISTAS_MID)}")
    with open(ruta, "rb") as f:
        d = f.read()
    if d[:4] != b"MThd":
        raise SystemExit("Eso no parece un archivo .mid")
    ntracks = int.from_bytes(d[10:12], "big")
    res = int.from_bytes(d[12:14], "big")
    pos = 8 + int.from_bytes(d[4:8], "big")
    tempos, pistas = [], {}
    for _ in range(ntracks):
        if d[pos:pos + 4] != b"MTrk":
            break
        fin = pos + 8 + int.from_bytes(d[pos + 4:pos + 8], "big")
        i, tick, estado, nombre, eventos = pos + 8, 0, 0, "", []
        while i < fin:
            delta = 0
            while True:
                b = d[i]
                i += 1
                delta = (delta << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            tick += delta
            if d[i] == 0xFF:
                tipo = d[i + 1]
                i += 2
                largo = 0
                while True:
                    b = d[i]
                    i += 1
                    largo = (largo << 7) | (b & 0x7F)
                    if not b & 0x80:
                        break
                datos = d[i:i + largo]
                i += largo
                if tipo == 0x03 and not nombre:
                    nombre = datos.decode("latin-1")
                elif tipo == 0x51 and largo == 3:
                    tempos.append((tick, 60000000 / int.from_bytes(datos, "big")))
            elif d[i] in (0xF0, 0xF7):
                i += 1
                largo = 0
                while True:
                    b = d[i]
                    i += 1
                    largo = (largo << 7) | (b & 0x7F)
                    if not b & 0x80:
                        break
                i += largo
            else:
                if d[i] & 0x80:
                    estado = d[i]
                    i += 1
                n = 1 if estado >> 4 in (0xC, 0xD) else 2
                if estado >> 4 in (0x8, 0x9):
                    nota, vel = d[i], d[i + 1]
                    eventos.append((tick, nota, estado >> 4 == 0x9 and vel > 0))
                i += n
        pistas[nombre] = eventos
        pos = fin
    if PISTAS_MID[inst] not in pistas:
        raise SystemExit(f"No encontre la pista {PISTAS_MID[inst]}. Hay: {', '.join(pistas)}")
    base = BASE_MID[dif]
    abiertas, notas = {}, []
    for tick, nota, on in pistas[PISTAS_MID[inst]]:
        if not base <= nota <= base + 4:
            continue
        if on:
            abiertas[nota] = tick
        elif nota in abiertas:
            ini = abiertas.pop(nota)
            largo = tick - ini
            notas.append((ini, nota - base, largo if largo >= res / 3 else 0))
    tempos = sorted(tempos)
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, tempos[0][1] if tempos else 120.0))
    return res, tempos, notas


def convertir(ruta_chart, dificultad="Expert", instrumento="Single", salida=None):
    """Convierte un .chart o .mid de Clone Hero. Devuelve (ruta_salida, cantidad_de_notas)."""
    dif = dificultad.capitalize()
    inst = instrumento
    if dif not in DIFICULTADES or inst not in INSTRUMENTOS:
        raise SystemExit(f"Dificultad {dif} o instrumento {inst} no valido")

    leer = leer_mid if ruta_chart.lower().endswith(".mid") else leer_chart
    res, tempos, crudas = leer(ruta_chart, dif, inst)
    bpm0 = tempos[0][1]
    notas = []
    for tick, carril, largo in crudas:
        beat = segundos(tick, tempos, res) * bpm0 / 60
        dur = (segundos(tick + largo, tempos, res) * bpm0 / 60 - beat) if largo else 0
        notas.append((round(beat, 4), carril, round(dur, 4)))

    notas.sort()
    salida = salida or os.path.join(os.path.dirname(os.path.abspath(ruta_chart)), "chart.txt")
    with open(salida, "w", encoding="utf-8") as f:
        f.write(f"# convertido de {os.path.basename(ruta_chart)} ({dif} {inst})\n")
        for beat, carril, dur in notas:
            f.write(f"{beat:g} {carril}" + (f" {dur:g}" if dur else "") + "\n")
    return salida, len(notas)


def main():
    p = argparse.ArgumentParser(description="Convierte .chart de Clone Hero a chart.txt")
    p.add_argument("archivo")
    p.add_argument("--dificultad", default="Expert")
    p.add_argument("--instrumento", default="Single")
    p.add_argument("--salida", default=None)
    a = p.parse_args()

    archivo = a.archivo
    if not os.path.isfile(archivo):
        # si la ruta no existe, busco .chart sueltos dentro de canciones/
        encontrados = []
        raiz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "canciones")
        for base, _, nombres in os.walk(raiz):
            for n in nombres:
                if n.lower().endswith((".chart", ".mid")):
                    encontrados.append(os.path.join(base, n))
        if len(encontrados) == 1:
            archivo = encontrados[0]
            print(f"Usando {archivo}")
        elif encontrados:
            raise SystemExit("Hay varios charts en 'canciones/', pasame la ruta de uno:\n  "
                             + "\n  ".join(encontrados))
        else:
            raise SystemExit(f"No encontre el archivo: {archivo}")

    salida, n = convertir(archivo, a.dificultad, a.instrumento, a.salida)
    print(f"Listo: {salida} ({n} notas)")


if __name__ == "__main__":
    main()
