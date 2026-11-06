"""
Guitar Hero + Arduino  -  version con menu de canciones.

Ejecutar:  python main.py

Estructura de carpetas:
    main.py
    puntajes.json                (se crea solo)
    canciones/
        ameba/
            info.json            (titulo, artista, bpm, offset, velocidad)
            Soda Stereo - Ameba.mp3   (cualquier .mp3/.ogg/.wav/.opus)
            chart.txt            (se crea solo si no existe)

Ademas, si una carpeta viene de Clone Hero (notes.chart o notes.mid + song.ini), el
juego solo la convierte y arma el info.json al arrancar.

Menu:    flechas arriba/abajo o carril 1/2  |  Enter o carril 3 = jugar
         R o carril 5 = grabar chart de la cancion elegida  |  E = editor de charts (editor.py)
         ESC = salir
Juego:   flechas IZQ/DER ajustan el offset (se guarda al terminar)  |  ESC = volver al menu
Teclado si no hay Arduino: A S D F G
"""
import json
import os
import random
import re
import time

import pygame

from convertir_chart import convertir, leer_chart, leer_mid

try:
    import serial
except ImportError:
    serial = None

# ---------- Configuracion ----------
PUERTO = "COM3"
BAUDIOS = 9600
CARRILES = 5
ANCHO, ALTO = 600, 800
LINEA_GOLPE = ALTO - 120
LEAD = 3.0               # segundos antes de que arranque la musica
VENT_PERFECT = 0.06
VENT_BUENO = 0.15
COLORES = [(0, 200, 0), (220, 0, 0), (240, 220, 0), (0, 120, 255), (255, 140, 0)]
TECLAS = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g]

BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA_CANCIONES = os.path.join(BASE, "canciones")
ARCHIVO_PUNTAJES = os.path.join(BASE, "puntajes.json")


# ---------- Entrada (Arduino o teclado) ----------
class Entrada:
    def __init__(self):
        self.ser = None
        self.estado = [False] * CARRILES
        if serial:
            try:
                self.ser = serial.Serial(PUERTO, BAUDIOS, timeout=0)
                time.sleep(2)
                print(f"Arduino conectado en {PUERTO}")
            except serial.SerialException:
                print("No se pudo abrir el puerto, uso teclado (A S D F G).")

    def actualizar(self):
        """Devuelve los carriles recien presionados en este frame."""
        previo = self.estado[:]
        if self.ser:
            while self.ser.in_waiting:
                linea = self.ser.readline().decode(errors="ignore").strip()
                if len(linea) == CARRILES and set(linea) <= {"0", "1"}:
                    self.estado = [c == "1" for c in linea]
        else:
            teclas = pygame.key.get_pressed()
            self.estado = [teclas[k] for k in TECLAS]
        return [i for i in range(CARRILES) if self.estado[i] and not previo[i]]


class Ctx:
    """Recursos compartidos entre pantallas."""


# ---------- Datos de canciones ----------
AUDIOS = (".mp3", ".ogg", ".wav", ".opus")


def mezclar_stems(ruta, archivos):
    """Mezcla varias pistas (guitar, bass, drums...) en un mezcla.wav y devuelve su ruta."""
    import wave
    import numpy as np
    destino = os.path.join(ruta, "mezcla.wav")
    mezcla = None
    for nombre in archivos:
        datos = np.frombuffer(pygame.mixer.Sound(os.path.join(ruta, nombre)).get_raw(), dtype=np.int16).astype(np.int32)
        if mezcla is None:
            mezcla = datos
        else:
            largo = max(len(mezcla), len(datos))
            mezcla = np.pad(mezcla, (0, largo - len(mezcla)))
            mezcla += np.pad(datos, (0, largo - len(datos)))
    mezcla = np.clip(mezcla, -32768, 32767).astype(np.int16)
    freq, _, canales = pygame.mixer.get_init()
    with wave.open(destino, "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(2)
        w.setframerate(freq)
        w.writeframes(mezcla.tobytes())
    print(f"Mezcla de {len(archivos)} pistas creada: {destino}")
    return destino


def buscar_audio(ruta):
    archivos = [n for n in sorted(os.listdir(ruta)) if n.lower().endswith(AUDIOS)]
    if "mezcla.wav" in archivos:
        return os.path.join(ruta, "mezcla.wav")
    if len(archivos) > 1:
        completo = [n for n in archivos if n.lower().startswith("song.")]
        if completo:
            return os.path.join(ruta, completo[0])
        try:
            return mezclar_stems(ruta, archivos)
        except Exception as e:
            print(f"[aviso] No pude mezclar las pistas de {ruta}: {e}")
    return os.path.join(ruta, archivos[0]) if archivos else None


def bpm_de_chart(ruta):
    """Primer BPM de un notes.chart / notes.mid de Clone Hero."""
    try:
        leer = leer_mid if ruta.lower().endswith(".mid") else leer_chart
        return round(leer(ruta, "Expert", "Single")[1][0][1], 3)
    except (SystemExit, IndexError, ValueError):
        return 100


def preparar_carpeta(ruta):
    """Si la carpeta viene de Clone Hero (notes.chart o notes.mid, song.ini), la deja lista
    para jugar: convierte el chart y arma un info.json si no hay."""
    ruta_info = os.path.join(ruta, "info.json")
    ruta_chart = os.path.join(ruta, "chart.txt")
    notes = next((os.path.join(ruta, n) for n in ("notes.chart", "notes.mid")
                  if os.path.isfile(os.path.join(ruta, n))), None)
    if not notes:
        return

    if not os.path.isfile(ruta_chart):
        try:
            salida, n = convertir(notes)
            print(f"Chart de Clone Hero convertido: {salida} ({n} notas)")
        except SystemExit as e:
            print(f"[aviso] No pude convertir {notes}: {e}")

    if not os.path.isfile(ruta_info):
        info = {"titulo": os.path.basename(ruta), "artista": "", "bpm": bpm_de_chart(notes)}
        ini = os.path.join(ruta, "song.ini")
        if os.path.isfile(ini):
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read(ini, encoding="utf-8")
                if cfg.has_section("song"):
                    info["titulo"] = cfg.get("song", "name", fallback=info["titulo"])
                    info["artista"] = cfg.get("song", "artist", fallback="")
                    delay = float(cfg.get("song", "delay", fallback=0))
                    info["offset"] = round(delay / 1000, 3)
            except (configparser.Error, ValueError):
                pass
        with open(ruta_info, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
        print(f"info.json creado para: {info['titulo']}")


def cargar_canciones():
    canciones = []
    if not os.path.isdir(CARPETA_CANCIONES):
        return canciones
    for carpeta in sorted(os.listdir(CARPETA_CANCIONES)):
        ruta = os.path.join(CARPETA_CANCIONES, carpeta)
        if not os.path.isdir(ruta):
            continue
        preparar_carpeta(ruta)
        ruta_info = os.path.join(ruta, "info.json")
        if not os.path.isfile(ruta_info):
            continue
        with open(ruta_info, encoding="utf-8") as f:
            info = json.load(f)
        audio = os.path.join(ruta, info["audio"]) if info.get("audio") else buscar_audio(ruta)
        canciones.append({
            "id": carpeta,
            "titulo": info.get("titulo", carpeta),
            "artista": info.get("artista", ""),
            "bpm": float(info.get("bpm", 100)),
            "offset": float(info.get("offset", 0.0)),
            "velocidad": float(info.get("velocidad", 400)),
            "audio": audio,
            "chart": os.path.join(ruta, "chart.txt"),
            "info_path": ruta_info,
        })
    return canciones


def guardar_offset(cancion):
    with open(cancion["info_path"], encoding="utf-8") as f:
        info = json.load(f)
    info["offset"] = round(cancion["offset"], 2)
    with open(cancion["info_path"], "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)


def cargar_chart(cancion):
    """Lista de [beat, carril, estado]. Si no hay chart, crea uno de prueba."""
    if not os.path.exists(cancion["chart"]):
        random.seed(1)
        with open(cancion["chart"], "w") as f:
            f.write("# chart de PRUEBA: una nota por beat\n")
            for beat in range(4, 360):
                f.write(f"{beat} {random.randrange(CARRILES)}\n")
    notas = []
    with open(cancion["chart"]) as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            partes = linea.split()
            dur = float(partes[2]) if len(partes) > 2 else 0.0
            # [beat, carril, estado, duracion_en_beats, sosteniendo]
            notas.append([float(partes[0]), int(partes[1]), None, dur, False])
    notas.sort()
    return notas


def guardar_chart(cancion, grabadas):
    if os.path.exists(cancion["chart"]):
        respaldo = cancion["chart"].replace("chart.txt", "chart_anterior.txt")
        os.replace(cancion["chart"], respaldo)
    with open(cancion["chart"], "w") as f:
        f.write(f"# BPM {cancion['bpm']:g}, offset {cancion['offset']:.2f}\n")
        for beat, carril in sorted(grabadas):
            f.write(f"{beat:g} {carril}\n")
    print(f"Chart guardado: {cancion['chart']} ({len(grabadas)} notas)")


def cargar_puntajes():
    if os.path.exists(ARCHIVO_PUNTAJES):
        try:
            with open(ARCHIVO_PUNTAJES, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def guardar_puntajes(puntajes):
    with open(ARCHIVO_PUNTAJES, "w", encoding="utf-8") as f:
        json.dump(puntajes, f, indent=2)


# ---------- Utilidades de dibujo ----------
def texto(ctx, s, fuente, color, x, y, centro=False):
    img = fuente.render(s, True, color)
    rect = img.get_rect()
    if centro:
        rect.midtop = (x, y)
    else:
        rect.topleft = (x, y)
    ctx.pantalla.blit(img, rect)


def pantalla_mensaje(ctx, mensaje):
    while True:
        ctx.reloj.tick(30)
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN):
                return
        ctx.pantalla.fill((20, 20, 30))
        texto(ctx, mensaje, ctx.chica, (255, 160, 160), ANCHO // 2, ALTO // 2 - 20, True)
        texto(ctx, "Apreta una tecla para volver", ctx.chica, (170, 170, 190), ANCHO // 2, ALTO // 2 + 20, True)
        pygame.display.flip()


# ---------- Pantalla: menu ----------
def menu(ctx, canciones, puntajes):
    """Devuelve (cancion, grabar) o None si se quiere salir."""
    sel = 0
    while True:
        ctx.reloj.tick(60)
        pulsados = ctx.entrada.actualizar()
        accion = None
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return None
                elif e.key == pygame.K_UP:
                    sel -= 1
                elif e.key == pygame.K_DOWN:
                    sel += 1
                elif e.key == pygame.K_RETURN:
                    accion = "jugar"
                elif e.key == pygame.K_r:
                    accion = "grabar"
                elif e.key == pygame.K_e:
                    accion = "editar"
        for c in pulsados:
            if c == 0:
                sel -= 1
            elif c == 1:
                sel += 1
            elif c == 2:
                accion = "jugar"
            elif c == 4:
                accion = "grabar"

        ctx.pantalla.fill((20, 20, 30))
        texto(ctx, "GUITAR HERO + ARDUINO", ctx.grande, (255, 255, 255), ANCHO // 2, 40, True)

        if not canciones:
            texto(ctx, "No hay canciones en la carpeta 'canciones'.", ctx.chica, (255, 160, 160), ANCHO // 2, 200, True)
            texto(ctx, "Cada una necesita su carpeta con info.json y un audio.", ctx.chica, (170, 170, 190), ANCHO // 2, 235, True)
        else:
            sel %= len(canciones)
            visibles = 8
            inicio = max(0, min(sel - visibles // 2, len(canciones) - visibles))
            for fila, idx in enumerate(range(inicio, min(inicio + visibles, len(canciones)))):
                c = canciones[idx]
                y = 130 + fila * 80
                if idx == sel:
                    pygame.draw.rect(ctx.pantalla, (50, 50, 90), (30, y - 8, ANCHO - 60, 70), border_radius=10)
                color = (255, 255, 255) if idx == sel else (160, 160, 180)
                texto(ctx, c["titulo"], ctx.fuente, color, 50, y)
                record = puntajes.get(c["id"], 0)
                detalle = f"{c['artista']}  |  {c['bpm']:g} BPM  |  Record: {record}"
                texto(ctx, detalle, ctx.chica, color, 50, y + 30)

        texto(ctx, "Arriba/abajo o carril 1/2: elegir   Enter o carril 3: jugar", ctx.chica, (170, 170, 190), ANCHO // 2, ALTO - 70, True)
        texto(ctx, "R o carril 5: grabar   E: editor de charts   ESC: salir", ctx.chica, (170, 170, 190), ANCHO // 2, ALTO - 40, True)
        pygame.display.flip()

        if accion and canciones:
            return canciones[sel], accion


# ---------- Pantalla: juego ----------
def jugar(ctx, cancion, grabar):
    """Devuelve un dict con el resultado. Claves: cerrar / error / completo / puntaje ..."""
    if not cancion["audio"]:
        return {"error": "No encontre ningun .mp3/.ogg/.wav en la carpeta de la cancion."}
    try:
        pygame.mixer.music.load(cancion["audio"])
    except pygame.error as e:
        return {"error": f"No pude cargar el audio: {e}"}

    seg_beat = 60.0 / cancion["bpm"]
    velocidad = cancion["velocidad"]
    ancho_carril = ANCHO // CARRILES
    notas = [] if grabar else cargar_chart(cancion)
    grabadas = set()
    puntaje = combo = max_combo = perfectos = buenos = fallos = 0
    mensaje, t_mensaje = "", 0.0
    offset_inicial = cancion["offset"]
    t0 = time.perf_counter()
    musica_ok = False
    completo = False
    cerrar = False
    corriendo = True
    t_prev = -LEAD
    resto = 0.0   # puntos fraccionarios por mantener notas largas

    while corriendo:
        ctx.reloj.tick(120)
        t = time.perf_counter() - t0 - LEAD
        dt = max(0.0, t - t_prev)
        t_prev = t
        if not musica_ok and t >= 0:
            pygame.mixer.music.play()
            musica_ok = True

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                cerrar = True
                corriendo = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    corriendo = False
                elif e.key == pygame.K_LEFT:
                    cancion["offset"] -= 0.01
                elif e.key == pygame.K_RIGHT:
                    cancion["offset"] += 0.01
        offset = cancion["offset"]

        for carril in ctx.entrada.actualizar():
            if grabar:
                beat = round((t - offset) / seg_beat * 2) / 2
                grabadas.add((beat, carril))
                mensaje, t_mensaje = f"grabado beat {beat:g}", time.perf_counter()
                continue
            cand = [n for n in notas
                    if n[1] == carril and n[2] is None
                    and abs(offset + n[0] * seg_beat - t) <= VENT_BUENO]
            if cand:
                n = min(cand, key=lambda n: abs(offset + n[0] * seg_beat - t))
                dif = abs(offset + n[0] * seg_beat - t)
                n[2] = "hit"
                n[4] = n[3] > 0   # si es nota larga, hay que mantenerla
                combo += 1
                max_combo = max(max_combo, combo)
                if dif <= VENT_PERFECT:
                    puntaje += 20 * (1 + combo // 10)
                    perfectos += 1
                    mensaje = "PERFECT"
                else:
                    puntaje += 10 * (1 + combo // 10)
                    buenos += 1
                    mensaje = "Bien"
                t_mensaje = time.perf_counter()
            else:
                combo = 0

        if not grabar:
            for n in notas:
                if n[4]:  # nota larga que se esta sosteniendo
                    fin = offset + (n[0] + n[3]) * seg_beat
                    if t >= fin or (not ctx.entrada.estado[n[1]] and t >= fin - 0.1):
                        n[4] = False
                        n[2] = "completa"
                        puntaje += 20
                        mensaje, t_mensaje = "Sostenida!", time.perf_counter()
                    elif not ctx.entrada.estado[n[1]]:
                        n[4] = False
                        n[2] = "soltada"
                        combo = 0
                        mensaje, t_mensaje = "Soltaste", time.perf_counter()
                    else:
                        resto += 25 * dt
                        if resto >= 1:
                            puntaje += int(resto)
                            resto -= int(resto)
            for n in notas:
                if n[2] is None and offset + n[0] * seg_beat < t - VENT_BUENO:
                    n[2] = "miss"
                    fallos += 1
                    combo = 0
                    mensaje, t_mensaje = "Fallaste", time.perf_counter()

        if musica_ok and t > 1 and not pygame.mixer.music.get_busy():
            completo = True
            corriendo = False

        # ----- Dibujo -----
        ctx.pantalla.fill((20, 20, 30))
        for i in range(CARRILES):
            x = i * ancho_carril
            pygame.draw.line(ctx.pantalla, (60, 60, 80), (x, 0), (x, ALTO))
            relleno = 0 if ctx.entrada.estado[i] else 3
            pygame.draw.circle(ctx.pantalla, COLORES[i], (x + ancho_carril // 2, LINEA_GOLPE), 28, relleno)
        if not grabar:
            for n in notas:
                activa = n[2] is None or (n[2] == "hit" and n[4])
                if not activa:
                    continue
                cx = n[1] * ancho_carril + ancho_carril // 2
                y = LINEA_GOLPE - (offset + n[0] * seg_beat - t) * velocidad
                if n[3] > 0:
                    y_fin = LINEA_GOLPE - (offset + (n[0] + n[3]) * seg_beat - t) * velocidad
                    y_cab = min(y, LINEA_GOLPE) if n[4] else y
                    if y_cab > -30 and y_fin < ALTO + 30:
                        base = COLORES[n[1]]
                        color_cola = base if n[4] else tuple(c // 2 + 40 for c in base)
                        pygame.draw.rect(ctx.pantalla, color_cola,
                                         (cx - 9, int(y_fin), 18, max(1, int(y_cab - y_fin))))
                    y = y_cab
                if -30 < y < ALTO + 30:
                    pygame.draw.circle(ctx.pantalla, COLORES[n[1]], (cx, int(y)), 24)
        texto(ctx, f"Puntaje {puntaje}   Combo {combo}", ctx.fuente, (255, 255, 255), 10, 10)
        texto(ctx, f"{cancion['titulo']}  |  Offset {offset:+.2f}s (flechas IZQ/DER)", ctx.chica, (170, 170, 190), 10, 45)
        if grabar:
            texto(ctx, "MODO GRABAR - ESC para guardar", ctx.chica, (255, 120, 120), 10, 70)
        if mensaje and time.perf_counter() - t_mensaje < 0.6:
            texto(ctx, mensaje, ctx.fuente, (255, 255, 255), ANCHO // 2, LINEA_GOLPE - 90, True)
        pygame.display.flip()

    pygame.mixer.music.stop()
    if grabar and grabadas:
        guardar_chart(cancion, grabadas)
    if abs(cancion["offset"] - offset_inicial) > 1e-9:
        guardar_offset(cancion)
    return {
        "cerrar": cerrar, "completo": completo and not grabar, "puntaje": puntaje,
        "perfectos": perfectos, "buenos": buenos, "fallos": fallos, "max_combo": max_combo,
    }


# ---------- Pantalla: resultados ----------
def resultados(ctx, cancion, res, nuevo_record, record_anterior):
    """Devuelve 'repetir', 'menu' o 'cerrar'."""
    while True:
        ctx.reloj.tick(60)
        pulsados = ctx.entrada.actualizar()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return "cerrar"
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    return "menu"
                if e.key == pygame.K_r:
                    return "repetir"
        for c in pulsados:
            if c == 2:
                return "menu"
            if c == 0:
                return "repetir"

        ctx.pantalla.fill((20, 20, 30))
        texto(ctx, "RESULTADOS", ctx.grande, (255, 255, 255), ANCHO // 2, 80, True)
        texto(ctx, cancion["titulo"], ctx.fuente, (200, 200, 220), ANCHO // 2, 140, True)
        texto(ctx, f"Puntaje: {res['puntaje']}", ctx.grande, (255, 255, 255), ANCHO // 2, 220, True)
        if nuevo_record:
            texto(ctx, "NUEVO RECORD!", ctx.fuente, (255, 220, 0), ANCHO // 2, 280, True)
        else:
            texto(ctx, f"Record: {record_anterior}", ctx.chica, (170, 170, 190), ANCHO // 2, 285, True)
        filas = [("Perfect", res["perfectos"]), ("Bien", res["buenos"]),
                 ("Fallos", res["fallos"]), ("Mejor combo", res["max_combo"])]
        for i, (nombre, valor) in enumerate(filas):
            texto(ctx, f"{nombre}: {valor}", ctx.fuente, (230, 230, 240), ANCHO // 2, 360 + i * 50, True)
        texto(ctx, "Enter o carril 3: menu   R o carril 1: repetir", ctx.chica, (170, 170, 190), ANCHO // 2, ALTO - 60, True)
        pygame.display.flip()


# ---------- Programa principal ----------
def main():
    pygame.init()
    pygame.mixer.init()
    ctx = Ctx()
    ctx.pantalla = pygame.display.set_mode((ANCHO, ALTO))
    pygame.display.set_caption("Guitar Hero + Arduino")
    ctx.reloj = pygame.time.Clock()
    ctx.grande = pygame.font.SysFont(None, 56)
    ctx.fuente = pygame.font.SysFont(None, 36)
    ctx.chica = pygame.font.SysFont(None, 26)
    ctx.entrada = Entrada()

    canciones = cargar_canciones()
    puntajes = cargar_puntajes()

    while True:
        eleccion = menu(ctx, canciones, puntajes)
        if eleccion is None:
            break
        cancion, accion_menu = eleccion

        if accion_menu == "editar":
            import editor
            if editor.editar(ctx, cancion) == "cerrar":
                pygame.quit()
                return
            continue
        grabar = accion_menu == "grabar"

        while True:
            res = jugar(ctx, cancion, grabar)
            if res.get("cerrar"):
                pygame.quit()
                return
            if res.get("error"):
                pantalla_mensaje(ctx, res["error"])
                break
            if grabar or not res["completo"]:
                break
            anterior = puntajes.get(cancion["id"], 0)
            nuevo = res["puntaje"] > anterior
            if nuevo:
                puntajes[cancion["id"]] = res["puntaje"]
                guardar_puntajes(puntajes)
            accion = resultados(ctx, cancion, res, nuevo, anterior)
            if accion == "cerrar":
                pygame.quit()
                return
            if accion == "menu":
                break
    pygame.quit()


if __name__ == "__main__":
    main()