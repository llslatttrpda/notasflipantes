"""
Guitar Hero + Arduino  -  colecciones de niveles con dificultades.

Ejecutar:  python main.py

Estructura de carpetas:
    main.py, editor.py, puntajes.json (se crea solo)
    canciones/
        90s/                       <- COLECCION (carpeta con canciones adentro)
            coleccion.json         (opcional: titulo, descripcion, orden, incluye)
            ameba/                 <- NIVEL (una cancion)
                info.json          (titulo, artista, bpm, offset, dificultades)
                Soda Stereo - Ameba.mp3
                chart.txt, chart_facil.txt, chart_dificil.txt ...
        suelta/                    <- carpeta con info.json directo: va a la coleccion "General"

info.json  -> "dificultades": {"facil": {"nombre", "chart", "velocidad",
              "ventana_perfect", "ventana_bueno", "multiplicador"}, "normal": {...}}
              Sin "dificultades" la cancion tiene una sola, "Normal" (chart.txt).
coleccion.json -> "incluye": ["90s/ameba"] arma colecciones con canciones de otras carpetas.

Menu:    colecciones -> canciones.  Arriba/abajo o carril 1/2 = elegir
         Enter o carril 3 = abrir / jugar  |  Izq/Der o carril 4 = cambiar dificultad
         ESC = volver  |  R = grabar chart  |  E = editor de charts
Juego:   flechas IZQ/DER ajustan el offset (se guarda al terminar)  |  ESC = volver al menu
Teclado si no hay Arduino: A S D F (4 carriles, ver config.py)
"""
import json
import os
import random
import time

import pygame

from config import CARRILES, COLORES

try:
    import serial
except ImportError:
    serial = None

# ---------- Configuracion ----------
PUERTO = "auto"   # "auto" busca el Arduino solo; o poner a mano, ej: "COM5"
BAUDIOS = 9600
ANCHO, ALTO = 600, 800
LINEA_GOLPE = ALTO - 120
LEAD = 3.0               # segundos antes de que arranque la musica
VENT_PERFECT = 0.06
VENT_BUENO = 0.15
PAUSA_FINAL = 1.0        # segundos tras la ultima nota antes de mostrar la pantalla de completado
FADE_PANTALLA = 1.5      # la pantalla de completado aparece de a poco en este tiempo
FADE_VOLUMEN = 1.0       # segundos que tarda la musica en bajar
VOLUMEN_FONDO = 0.3      # volumen al que queda la musica de fondo
TECLAS = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g][:CARRILES]

BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA_CANCIONES = os.path.join(BASE, "canciones")
ARCHIVO_PUNTAJES = os.path.join(BASE, "puntajes.json")


# ---------- Entrada (Arduino o teclado) ----------
def listar_puertos():
    if not serial:
        return []
    from serial.tools import list_ports
    return [f"{p.device} ({p.description})" for p in list_ports.comports()]


def detectar_puerto():
    """Busca un puerto que parezca un Arduino (o un chip USB-serie comun en clones)."""
    if not serial:
        return None
    from serial.tools import list_ports
    for p in list_ports.comports():
        desc = f"{p.description} {p.manufacturer or ''}".lower()
        if any(k in desc for k in ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "ftdi")):
            return p.device
    return None


class Entrada:
    def __init__(self):
        self.ser = None
        self.estado = [False] * CARRILES
        self.avisado = False
        if serial:
            candidatos = [] if PUERTO == "auto" else [PUERTO]
            auto = detectar_puerto()
            if auto and auto not in candidatos:
                candidatos.append(auto)
            for puerto in candidatos:
                try:
                    self.ser = serial.Serial(puerto, BAUDIOS, timeout=0)
                    time.sleep(2)  # el Arduino se reinicia al abrir el puerto
                    print(f"Arduino conectado en {puerto}")
                    break
                except serial.SerialException as e:
                    print(f"No pude abrir {puerto}: {e}")
            if not self.ser:
                print("Puertos disponibles:", listar_puertos() or "ninguno")
                print("Sin Arduino: uso el teclado (A S D F).")

    def actualizar(self):
        """Devuelve los carriles recien presionados en este frame."""
        previo = self.estado[:]
        if self.ser:
            while self.ser.in_waiting:
                linea = self.ser.readline().decode(errors="ignore").strip()
                if len(linea) == CARRILES and set(linea) <= {"0", "1"}:
                    self.estado = [c == "1" for c in linea]
                elif len(linea) > CARRILES and set(linea) <= {"0", "1"} and not self.avisado:
                    self.avisado = True
                    print(f"AVISO: el Arduino manda {len(linea)} botones y el juego espera {CARRILES}. "
                          "Subi el sketch actualizado (guitar_hero.ino).")
        else:
            teclas = pygame.key.get_pressed()
            self.estado = [teclas[k] for k in TECLAS]
        return [i for i in range(CARRILES) if self.estado[i] and not previo[i]]


class Ctx:
    """Recursos compartidos entre pantallas."""


# ---------- Datos de canciones ----------
def buscar_audio(ruta):
    for nombre in sorted(os.listdir(ruta)):
        if nombre.lower().endswith((".mp3", ".ogg", ".wav")):
            return os.path.join(ruta, nombre)
    return None


def leer_dificultades(ruta, info):
    """Una dificultad por cada entrada de info['dificultades']; si no hay, una sola 'Normal'."""
    cfgs = info.get("dificultades")
    con_dificultades = bool(cfgs)
    if not cfgs:
        cfgs = {"normal": {}}
    velocidad_base = float(info.get("velocidad", 400))
    resultado = []
    for clave, cfg in cfgs.items():
        cfg = cfg or {}
        chart_defecto = f"chart_{clave}.txt" if con_dificultades else "chart.txt"
        resultado.append({
            "dif_id": clave,
            "dificultad": cfg.get("nombre", clave.capitalize()),
            "chart": os.path.join(ruta, cfg.get("chart", chart_defecto)),
            "velocidad": float(cfg.get("velocidad", velocidad_base)),
            "vent_perfect": float(cfg.get("ventana_perfect", VENT_PERFECT)),
            "vent_bueno": float(cfg.get("ventana_bueno", VENT_BUENO)),
            "multiplicador": float(cfg.get("multiplicador", 1.0)),
        })
    return resultado


def leer_cancion(ruta, id_rel):
    ruta_info = os.path.join(ruta, "info.json")
    try:
        with open(ruta_info, encoding="utf-8") as f:
            info = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        print(f"Ignoro {ruta_info}: no es un JSON valido ({e})")
        return None
    audio = os.path.join(ruta, info["audio"]) if info.get("audio") else buscar_audio(ruta)
    return {
        "id": id_rel,
        "titulo": info.get("titulo", os.path.basename(ruta)),
        "artista": info.get("artista", ""),
        "bpm": float(info.get("bpm", 100)),
        "offset": float(info.get("offset", 0.0)),
        "audio": audio,
        "info_path": ruta_info,
        "dificultades": leer_dificultades(ruta, info),
    }


def cargar_colecciones():
    """Devuelve una lista de colecciones: {'titulo', 'descripcion', 'canciones': [...]}"""
    if not os.path.isdir(CARPETA_CANCIONES):
        return []
    por_id, sueltas, colecciones = {}, [], []
    for nombre in sorted(os.listdir(CARPETA_CANCIONES)):
        ruta = os.path.join(CARPETA_CANCIONES, nombre)
        if not os.path.isdir(ruta):
            continue
        if os.path.isfile(os.path.join(ruta, "info.json")):   # cancion suelta
            c = leer_cancion(ruta, nombre)
            if c:
                por_id[c["id"]] = c
                sueltas.append(c)
            continue
        meta = {}
        ruta_meta = os.path.join(ruta, "coleccion.json")
        if os.path.isfile(ruta_meta):
            try:
                with open(ruta_meta, encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                print(f"Ignoro {ruta_meta}: no es un JSON valido ({e})")
        col = {
            "id": nombre,
            "titulo": meta.get("titulo", nombre),
            "descripcion": meta.get("descripcion", ""),
            "orden": meta.get("orden", 100),
            "incluye": meta.get("incluye", []),
            "canciones": [],
        }
        for sub in sorted(os.listdir(ruta)):
            ruta_sub = os.path.join(ruta, sub)
            if os.path.isdir(ruta_sub) and os.path.isfile(os.path.join(ruta_sub, "info.json")):
                c = leer_cancion(ruta_sub, f"{nombre}/{sub}")
                if c:
                    por_id[c["id"]] = c
                    col["canciones"].append(c)
        colecciones.append(col)
    for col in colecciones:   # canciones de otras carpetas referenciadas con "incluye"
        for ref in col["incluye"]:
            c = por_id.get(ref)
            if c is None:
                print(f"Coleccion '{col['titulo']}': no encuentro la cancion '{ref}'")
            elif c not in col["canciones"]:
                col["canciones"].append(c)
    colecciones = [c for c in colecciones if c["canciones"]]
    colecciones.sort(key=lambda c: (c["orden"], c["titulo"].lower()))
    if sueltas:
        colecciones.insert(0, {"id": "general", "titulo": "General", "descripcion": "Canciones sueltas",
                               "orden": 0, "incluye": [], "canciones": sueltas})
    return colecciones


def construir_nivel(cancion, idx):
    """Combina la cancion con la dificultad elegida. Es lo que usan jugar() y el editor."""
    nivel = {k: v for k, v in cancion.items() if k != "dificultades"}
    nivel.update(cancion["dificultades"][idx])
    nivel["id_puntaje"] = f"{cancion['id']}|{nivel['dif_id']}"
    nivel["_base"] = cancion   # para devolverle el offset calibrado
    return nivel


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
    notas, vistos, pasadas = [], set(), 0
    with open(cancion["chart"]) as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            partes = linea.split()
            beat, carril = float(partes[0]), int(partes[1])
            dur = float(partes[2]) if len(partes) > 2 else 0.0
            if carril >= CARRILES:   # chart hecho con mas carriles: pasa al ultimo
                carril = CARRILES - 1
                pasadas += 1
            if (beat, carril) in vistos:
                continue
            vistos.add((beat, carril))
            # [beat, carril, estado, duracion_en_beats, sosteniendo]
            notas.append([beat, carril, None, dur, False])
    if pasadas:
        print(f"{os.path.basename(cancion['chart'])}: {pasadas} notas de carriles que ya no existen "
              f"se pasaron al carril {CARRILES}.")
    notas.sort()
    return notas


def guardar_chart(cancion, grabadas):
    if os.path.exists(cancion["chart"]):
        base, ext = os.path.splitext(cancion["chart"])
        os.replace(cancion["chart"], f"{base}_anterior{ext}")
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
def texto(ctx, s, fuente, color, x, y, centro=False, destino=None):
    destino = destino or ctx.pantalla
    img = fuente.render(s, True, color)
    rect = img.get_rect()
    if centro:
        rect.midtop = (x, y)
    else:
        rect.topleft = (x, y)
    destino.blit(img, rect)


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
def ventana_lista(sel, total, visibles):
    return max(0, min(sel - visibles // 2, total - visibles))


def menu(ctx, colecciones, puntajes, estado):
    """Colecciones -> canciones (con selector de dificultad).
    Devuelve (nivel, accion) con accion 'jugar' / 'grabar' / 'editar', o None para salir."""
    gris = (170, 170, 190)
    while True:
        ctx.reloj.tick(60)
        pulsados = ctx.entrada.actualizar()
        mov = cambiar = 0
        entrar = atras = False
        accion = None
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    atras = True
                elif e.key == pygame.K_UP:
                    mov -= 1
                elif e.key == pygame.K_DOWN:
                    mov += 1
                elif e.key == pygame.K_LEFT:
                    cambiar -= 1
                elif e.key == pygame.K_RIGHT:
                    cambiar += 1
                elif e.key == pygame.K_RETURN:
                    entrar = True
                elif e.key == pygame.K_r:
                    accion = "grabar"
                elif e.key == pygame.K_e:
                    accion = "editar"
        for c in pulsados:
            if c == 0:
                mov -= 1
            elif c == 1:
                mov += 1
            elif c == 2:
                entrar = True
            elif c == 3:
                cambiar += 1
            elif c == 4:
                atras = True

        ctx.pantalla.fill((20, 20, 30))
        texto(ctx, "GUITAR HERO + ARDUINO", ctx.grande, (255, 255, 255), ANCHO // 2, 30, True)

        if not colecciones:
            texto(ctx, "No hay canciones en la carpeta 'canciones'.", ctx.chica, (255, 160, 160), ANCHO // 2, 200, True)
            texto(ctx, "Mira la estructura de carpetas al principio de main.py.", ctx.chica, gris, ANCHO // 2, 235, True)
            pygame.display.flip()
            if atras:
                return None
            continue

        visibles = 7
        if not estado["en_lista"]:
            # ----- Pantalla de colecciones -----
            estado["col"] = (estado["col"] + mov) % len(colecciones)
            if entrar:
                estado["en_lista"] = True
                estado["sel"] = 0
            elif atras:
                return None
            texto(ctx, "Colecciones", ctx.fuente, (200, 200, 220), ANCHO // 2, 100, True)
            inicio = ventana_lista(estado["col"], len(colecciones), visibles)
            for fila, idx in enumerate(range(inicio, min(inicio + visibles, len(colecciones)))):
                col = colecciones[idx]
                y = 150 + fila * 80
                sel = idx == estado["col"]
                if sel:
                    pygame.draw.rect(ctx.pantalla, (50, 50, 90), (30, y - 8, ANCHO - 60, 70), border_radius=10)
                color = (255, 255, 255) if sel else (160, 160, 180)
                texto(ctx, col["titulo"], ctx.fuente, color, 50, y)
                detalle = f"{len(col['canciones'])} canciones"
                if col["descripcion"]:
                    detalle += f"  |  {col['descripcion']}"
                texto(ctx, detalle, ctx.chica, color, 50, y + 30)
            texto(ctx, "Arriba/abajo o carril 1/2: elegir   Enter o carril 3: abrir", ctx.chica, gris, ANCHO // 2, ALTO - 70, True)
            texto(ctx, "ESC: salir", ctx.chica, gris, ANCHO // 2, ALTO - 40, True)
        else:
            # ----- Pantalla de canciones de una coleccion -----
            col = colecciones[estado["col"]]
            canciones = col["canciones"]
            estado["sel"] = (estado["sel"] + mov) % len(canciones)
            cancion = canciones[estado["sel"]]
            if cambiar:
                actual = estado["dif"].get(cancion["id"], 0)
                estado["dif"][cancion["id"]] = (actual + cambiar) % len(cancion["dificultades"])
            if atras:
                if len(colecciones) > 1:
                    estado["en_lista"] = False
                else:
                    return None
            elif entrar or accion:
                idx = estado["dif"].get(cancion["id"], 0)
                return construir_nivel(cancion, idx), accion or "jugar"
            texto(ctx, col["titulo"], ctx.fuente, (200, 200, 220), ANCHO // 2, 100, True)
            inicio = ventana_lista(estado["sel"], len(canciones), visibles)
            for fila, idx in enumerate(range(inicio, min(inicio + visibles, len(canciones)))):
                c = canciones[idx]
                y = 150 + fila * 80
                sel = idx == estado["sel"]
                d = c["dificultades"][estado["dif"].get(c["id"], 0)]
                if sel:
                    pygame.draw.rect(ctx.pantalla, (50, 50, 90), (30, y - 8, ANCHO - 60, 70), border_radius=10)
                color = (255, 255, 255) if sel else (160, 160, 180)
                texto(ctx, c["titulo"], ctx.fuente, color, 50, y)
                etiqueta = d["dificultad"]
                if sel and len(c["dificultades"]) > 1:
                    etiqueta = f"<  {etiqueta}  >"
                ancho_et = ctx.chica.size(etiqueta)[0]
                texto(ctx, etiqueta, ctx.chica, (255, 220, 0) if sel else color, ANCHO - 50 - ancho_et, y + 6)
                clave = f"{c['id']}|{d['dif_id']}"
                detalle = f"{c['artista']}  |  {c['bpm']:g} BPM  |  Record: {puntajes.get(clave, 0)}"
                texto(ctx, detalle, ctx.chica, color, 50, y + 30)
            texto(ctx, "Arriba/abajo o carril 1/2: elegir   Izq/Der o carril 4: dificultad", ctx.chica, gris, ANCHO // 2, ALTO - 100, True)
            texto(ctx, "Enter o carril 3: jugar   R: grabar chart   E: editor", ctx.chica, gris, ANCHO // 2, ALTO - 70, True)
            texto(ctx, "ESC: volver", ctx.chica, gris, ANCHO // 2, ALTO - 40, True)
        pygame.display.flip()


# ---------- Pantalla: juego ----------
def jugar(ctx, cancion, grabar):
    """Devuelve un dict con el resultado. Claves: cerrar / error / completo / puntaje ..."""
    if not cancion["audio"]:
        return {"error": "No encontre ningun .mp3/.ogg/.wav en la carpeta de la cancion."}
    try:
        pygame.mixer.music.load(cancion["audio"])
        pygame.mixer.music.set_volume(1.0)
    except pygame.error as e:
        return {"error": f"No pude cargar el audio: {e}"}

    seg_beat = 60.0 / cancion["bpm"]
    vp, vb = cancion["vent_perfect"], cancion["vent_bueno"]   # ventanas segun la dificultad
    mult = cancion["multiplicador"]
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
    t_fin = None  # momento en que se resolvio la ultima nota del chart
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
                    and abs(offset + n[0] * seg_beat - t) <= vb]
            if cand:
                n = min(cand, key=lambda n: abs(offset + n[0] * seg_beat - t))
                dif = abs(offset + n[0] * seg_beat - t)
                n[2] = "hit"
                n[4] = n[3] > 0   # si es nota larga, hay que mantenerla
                combo += 1
                max_combo = max(max_combo, combo)
                if dif <= vp:
                    puntaje += int(20 * (1 + combo // 10) * mult)
                    perfectos += 1
                    mensaje = "PERFECT"
                else:
                    puntaje += int(10 * (1 + combo // 10) * mult)
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
                        puntaje += int(20 * mult)
                        mensaje, t_mensaje = "Sostenida!", time.perf_counter()
                    elif not ctx.entrada.estado[n[1]]:
                        n[4] = False
                        n[2] = "soltada"
                        combo = 0
                        mensaje, t_mensaje = "Soltaste", time.perf_counter()
                    else:
                        resto += 25 * dt * mult
                        if resto >= 1:
                            puntaje += int(resto)
                            resto -= int(resto)
            for n in notas:
                if n[2] is None and offset + n[0] * seg_beat < t - vb:
                    n[2] = "miss"
                    fallos += 1
                    combo = 0
                    mensaje, t_mensaje = "Fallaste", time.perf_counter()

        # El final lo marca el chart: cuando ya no queda ninguna nota por resolver
        if not grabar and notas and t_fin is None and all(n[2] is not None and not n[4] for n in notas):
            t_fin = t
        if t_fin is not None and t - t_fin >= PAUSA_FINAL:
            completo = True
            corriendo = False
        elif musica_ok and t > 1 and not pygame.mixer.music.get_busy():
            completo = True   # (se termino la cancion antes que el chart)
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
        texto(ctx, f"{cancion['titulo']} [{cancion['dificultad']}]  |  Offset {offset:+.2f}s (flechas IZQ/DER)", ctx.chica, (170, 170, 190), 10, 45)
        if grabar:
            texto(ctx, "MODO GRABAR - ESC para guardar", ctx.chica, (255, 120, 120), 10, 70)
        if mensaje and time.perf_counter() - t_mensaje < 0.6:
            texto(ctx, mensaje, ctx.fuente, (255, 255, 255), ANCHO // 2, LINEA_GOLPE - 90, True)
        pygame.display.flip()

    fondo = ctx.pantalla.copy()   # ultimo cuadro, para el fundido de la pantalla final
    if not (completo and not grabar):
        pygame.mixer.music.stop()   # si se completo el chart, el tema sigue sonando de fondo
    if grabar and grabadas:
        guardar_chart(cancion, grabadas)
    if abs(cancion["offset"] - offset_inicial) > 1e-9:
        guardar_offset(cancion)
    return {
        "cerrar": cerrar, "completo": completo and not grabar, "puntaje": puntaje,
        "perfectos": perfectos, "buenos": buenos, "fallos": fallos, "max_combo": max_combo,
        "fondo": fondo,
    }


# ---------- Pantalla: resultados ----------
def resultados(ctx, cancion, res, nuevo_record, record_anterior):
    """Aparece de a poco sobre el ultimo cuadro del juego, mientras la musica baja
    a VOLUMEN_FONDO y sigue sonando de fondo. Devuelve 'repetir', 'menu' o 'cerrar'."""
    fondo = res.get("fondo")
    oscuro = pygame.Surface((ANCHO, ALTO))
    oscuro.fill((10, 10, 20))
    t_ini = time.perf_counter()
    while True:
        ctx.reloj.tick(60)
        pasado = time.perf_counter() - t_ini
        # La musica baja a VOLUMEN_FONDO en FADE_VOLUMEN segundos y se queda sonando
        prog_vol = min(1.0, pasado / FADE_VOLUMEN)
        pygame.mixer.music.set_volume(1.0 - (1.0 - VOLUMEN_FONDO) * prog_vol)
        prog = min(1.0, pasado / FADE_PANTALLA)
        # Hasta que termina el fundido se ignoran los botones (todavia se esta tocando)
        listo = pasado >= FADE_PANTALLA

        pulsados = ctx.entrada.actualizar()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return "cerrar"
            if e.type == pygame.KEYDOWN and listo:
                if e.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    return "menu"
                if e.key == pygame.K_r:
                    return "repetir"
        if listo:
            for c in pulsados:
                if c == 2:
                    return "menu"
                if c == 0:
                    return "repetir"

        if fondo:
            ctx.pantalla.blit(fondo, (0, 0))
        else:
            ctx.pantalla.fill((20, 20, 30))
        oscuro.set_alpha(int(225 * prog))
        ctx.pantalla.blit(oscuro, (0, 0))

        capa = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        texto(ctx, "COMPLETADO", ctx.grande, (255, 255, 255), ANCHO // 2, 80, True, capa)
        texto(ctx, f"{cancion['titulo']}  -  {cancion['dificultad']}", ctx.fuente, (200, 200, 220), ANCHO // 2, 140, True, capa)
        texto(ctx, f"Puntaje: {res['puntaje']}", ctx.grande, (255, 255, 255), ANCHO // 2, 220, True, capa)
        if nuevo_record:
            texto(ctx, "NUEVO RECORD!", ctx.fuente, (255, 220, 0), ANCHO // 2, 280, True, capa)
        else:
            texto(ctx, f"Record: {record_anterior}", ctx.chica, (170, 170, 190), ANCHO // 2, 285, True, capa)
        filas = [("Perfect", res["perfectos"]), ("Bien", res["buenos"]),
                 ("Fallos", res["fallos"]), ("Mejor combo", res["max_combo"])]
        for i, (nombre, valor) in enumerate(filas):
            texto(ctx, f"{nombre}: {valor}", ctx.fuente, (230, 230, 240), ANCHO // 2, 360 + i * 50, True, capa)
        texto(ctx, "Enter o carril 3: menu   R o carril 1: repetir", ctx.chica, (170, 170, 190), ANCHO // 2, ALTO - 60, True, capa)
        capa.set_alpha(int(255 * prog))
        ctx.pantalla.blit(capa, (0, 0))
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

    colecciones = cargar_colecciones()
    puntajes = cargar_puntajes()
    estado = {"col": 0, "sel": 0, "en_lista": len(colecciones) == 1, "dif": {}}

    while True:
        eleccion = menu(ctx, colecciones, puntajes, estado)
        if eleccion is None:
            break
        cancion, accion_menu = eleccion

        if accion_menu == "editar":
            import editor
            res_ed = editor.editar(ctx, cancion)
            cancion["_base"]["offset"] = cancion["offset"]   # conservar el offset calibrado
            if res_ed == "cerrar":
                pygame.quit()
                return
            continue
        grabar = accion_menu == "grabar"

        while True:
            res = jugar(ctx, cancion, grabar)
            cancion["_base"]["offset"] = cancion["offset"]
            if res.get("cerrar"):
                pygame.quit()
                return
            if res.get("error"):
                pantalla_mensaje(ctx, res["error"])
                break
            if grabar or not res["completo"]:
                break
            anterior = puntajes.get(cancion["id_puntaje"], 0)
            nuevo = res["puntaje"] > anterior
            if nuevo:
                puntajes[cancion["id_puntaje"]] = res["puntaje"]
                guardar_puntajes(puntajes)
            accion = resultados(ctx, cancion, res, nuevo, anterior)
            pygame.mixer.music.stop()
            pygame.mixer.music.set_volume(1.0)
            if accion == "cerrar":
                pygame.quit()
                return
            if accion == "menu":
                break
    pygame.quit()


if __name__ == "__main__":
    main()