"""
Editor de charts para Guitar Hero + Arduino.
Se abre desde el menu de main.py con la tecla E.

Vista: el tiempo corre hacia ARRIBA (igual que en el juego). La linea de abajo
es el cursor. Los beats futuros estan arriba, los pasados abajo.

Controles:
    Flecha arriba/abajo o rueda del mouse : mover el cursor (segun la precision)
    Re Pag / Av Pag                       : mover 4 beats
    Inicio                                : ir al principio
    A S D F G (o botones Arduino) / clic  : poner o quitar una nota
    Arrastrar con el mouse hacia arriba   : nota LARGA (formato chart: "beat carril duracion")
    Supr                                  : borrar todas las notas del beat actual
    1 2 3 4                               : precision 1, 1/2, 1/4, 1/8 de beat
    Espacio                               : reproducir desde el cursor
                                            (mientras suena, las teclas AGREGAN notas en vivo)
    + / -                                 : zoom
    T                                     : tick sonoro al pasar por cada nota
    , y .                                 : offset -0.01 / +0.01 s
    Ctrl+S guardar   Ctrl+Z deshacer   ESC detener / salir
"""
import json
import math
import os
import time
from array import array

import pygame

CARRILES = 5
ANCHO, ALTO = 600, 800
HEADER = 90
Y_CURSOR = ALTO - 170
Y_FIN = Y_CURSOR + 50
COLORES = [(0, 200, 0), (220, 0, 0), (240, 220, 0), (0, 120, 255), (255, 140, 0)]


def leer_chart(ruta):
    notas = set()
    if os.path.exists(ruta):
        with open(ruta) as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                partes = linea.split()
                dur = round(float(partes[2]), 4) if len(partes) > 2 else 0.0
                notas.add((round(float(partes[0]), 4), int(partes[1]), dur))
    return notas


def hacer_click():
    """Sonido corto de 'tick' generado a mano (sin numpy)."""
    init = pygame.mixer.get_init()
    if not init:
        return None
    freq, formato, canales = init
    if formato != -16:
        return None
    n = int(freq * 0.03)
    muestras = array("h")
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * 1800 * i / freq) * (1 - i / n) ** 2)
        for _ in range(canales):
            muestras.append(v)
    return pygame.mixer.Sound(buffer=muestras.tobytes())


class Editor:
    def __init__(self, ctx, cancion):
        self.ctx = ctx
        self.c = cancion
        self.seg = 60.0 / cancion["bpm"]
        self.notas = leer_chart(cancion["chart"])
        self.historial = []
        self.cursor = 0.0
        self.div = 2
        self.ppb = 120.0
        self.sonando = False
        self.cursor0 = 0.0
        self.t_wall0 = 0.0
        self.cambios = False
        self.cambio_offset = False
        self.respaldo_hecho = False
        self.tick_on = True
        self.click = hacer_click()
        self.flash = [0.0] * CARRILES
        self.mensaje = ""
        self.t_mensaje = 0.0
        self.confirmar_salida = False
        self.vivo = {}         # carril -> beat (sin ajustar) en que se apreto la tecla en vivo
        self.arrastre = None   # (carril, beat inicial) mientras se arrastra con el mouse
        self.audio_ok = False
        self.fuente_h = pygame.font.SysFont(None, 22)
        if cancion["audio"]:
            try:
                pygame.mixer.music.load(cancion["audio"])
                self.audio_ok = True
            except pygame.error:
                pass

    # ---------- utilidades ----------
    @property
    def snap(self):
        return 1.0 / self.div

    def avisar(self, texto):
        self.mensaje = texto
        self.t_mensaje = time.perf_counter()

    def ajustar(self, beat):
        return round(round(beat / self.snap) * self.snap, 4)

    def mover(self, delta):
        self.cursor = max(0.0, self.ajustar(self.cursor + delta))

    def y_de(self, beat):
        return Y_CURSOR - (beat - self.cursor) * self.ppb

    def registrar(self):
        self.historial.append(frozenset(self.notas))
        if len(self.historial) > 200:
            self.historial.pop(0)
        self.cambios = True

    def alternar(self, beat, carril):
        if beat < 0:
            return
        beat = round(beat, 4)
        existente = self.buscar(beat, carril)
        self.registrar()
        if existente:
            self.notas.remove(existente)
        else:
            self.notas.add((beat, carril, 0.0))

    def agregar(self, beat, carril):
        beat = round(beat, 4)
        if beat >= 0 and not self.buscar(beat, carril):
            self.registrar()
            self.notas.add((beat, carril, 0.0))

    def buscar(self, beat, carril):
        for n in self.notas:
            if n[1] == carril and abs(n[0] - beat) < 1e-6:
                return n
        return None

    def poner_larga(self, beat, carril, dur):
        """Crea (o reemplaza) una nota larga que empieza en 'beat' y dura 'dur' beats."""
        beat = round(beat, 4)
        if beat < 0:
            return
        self.registrar()
        existente = self.buscar(beat, carril)
        if existente:
            self.notas.remove(existente)
        self.notas.add((beat, carril, round(dur, 4)))

    def cerrar_larga(self, carril, inicio):
        """Al soltar una tecla en vivo: si se mantuvo >= medio beat, la nota pasa a ser larga."""
        ini = self.ajustar(inicio)
        dur = self.ajustar(self.cursor) - ini
        if dur >= 0.5:
            self.poner_larga(ini, carril, dur)

    def deshacer(self):
        if self.historial:
            self.notas = set(self.historial.pop())
            self.cambios = True
            self.avisar("Deshecho")
        else:
            self.avisar("Nada para deshacer")

    def borrar_beat(self):
        b = self.ajustar(self.cursor)
        quitar = {n for n in self.notas if abs(n[0] - b) < 1e-6}
        if quitar:
            self.registrar()
            self.notas -= quitar

    # ---------- reproduccion ----------
    def iniciar(self):
        if not self.audio_ok:
            self.avisar("No hay audio para reproducir")
            return
        t_audio = max(0.0, self.c["offset"] + self.cursor * self.seg)
        try:
            pygame.mixer.music.play(start=t_audio)
        except pygame.error as e:
            self.avisar(f"No pude reproducir: {e}")
            return
        self.t_wall0 = time.perf_counter()
        self.cursor0 = (t_audio - self.c["offset"]) / self.seg
        self.cursor = self.cursor0
        self.sonando = True

    def detener(self):
        pygame.mixer.music.stop()
        for carril, inicio in list(self.vivo.items()):
            self.cerrar_larga(carril, inicio)
        self.vivo.clear()
        self.sonando = False
        self.cursor = max(0.0, self.ajustar(self.cursor))

    # ---------- guardado ----------
    def guardar(self):
        chart = self.c["chart"]
        if not self.respaldo_hecho and os.path.exists(chart):
            os.replace(chart, chart.replace("chart.txt", "chart_anterior.txt"))
        self.respaldo_hecho = True
        with open(chart, "w") as f:
            f.write(f"# BPM {self.c['bpm']:g}, offset {self.c['offset']:.2f}\n")
            for beat, carril, dur in sorted(self.notas):
                if dur > 0:
                    f.write(f"{beat:g} {carril} {dur:g}\n")
                else:
                    f.write(f"{beat:g} {carril}\n")
        if self.cambio_offset:
            with open(self.c["info_path"], encoding="utf-8") as f:
                info = json.load(f)
            info["offset"] = round(self.c["offset"], 2)
            with open(self.c["info_path"], "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2, ensure_ascii=False)
        self.cambios = False
        self.cambio_offset = False
        self.avisar(f"Guardado ({len(self.notas)} notas)")

    # ---------- dibujo ----------
    def texto(self, s, fuente, color, x, y):
        self.ctx.pantalla.blit(fuente.render(s, True, color), (x, y))

    def dibujar(self):
        p = self.ctx.pantalla
        ancho = ANCHO // CARRILES
        p.fill((20, 20, 30))

        p.set_clip(pygame.Rect(0, HEADER, ANCHO, Y_FIN - HEADER))
        beat_lo = self.cursor - (Y_FIN - Y_CURSOR) / self.ppb
        beat_hi = self.cursor + (Y_CURSOR - HEADER) / self.ppb
        i0 = math.floor(beat_lo / self.snap)
        i1 = math.ceil(beat_hi / self.snap)
        for i in range(i0, i1 + 1):
            b = i * self.snap
            if b < 0:
                continue
            y = int(self.y_de(b))
            entero = abs(b - round(b)) < 1e-9
            compas = entero and round(b) % 4 == 0
            if compas:
                pygame.draw.line(p, (110, 110, 150), (0, y), (ANCHO, y), 2)
                self.texto(str(round(b)), self.fuente_h, (150, 150, 190), 4, y - 16)
            elif entero:
                pygame.draw.line(p, (70, 70, 100), (0, y), (ANCHO, y))
            elif self.snap * self.ppb >= 14:
                pygame.draw.line(p, (40, 40, 58), (0, y), (ANCHO, y))
        for i in range(1, CARRILES):
            pygame.draw.line(p, (60, 60, 80), (i * ancho, HEADER), (i * ancho, Y_FIN))
        for beat, carril, dur in self.notas:
            y = self.y_de(beat)
            cx = carril * ancho + ancho // 2
            if dur > 0:
                y2 = self.y_de(beat + dur)
                if y2 < Y_FIN and y > HEADER:
                    cola = tuple(c // 2 + 40 for c in COLORES[carril])
                    pygame.draw.rect(p, cola, (cx - 8, int(y2), 16, max(1, int(y - y2))))
            if HEADER - 20 < y < Y_FIN + 20:
                pygame.draw.circle(p, COLORES[carril], (cx, int(y)), 18)
                pygame.draw.circle(p, (255, 255, 255), (cx, int(y)), 18, 2)
        if self.arrastre:  # vista previa de la nota larga que se esta arrastrando
            carril, ini = self.arrastre
            cx = carril * ancho + ancho // 2
            y_ini = self.y_de(ini)
            y_mouse = pygame.mouse.get_pos()[1]
            if y_mouse < y_ini:
                pygame.draw.rect(p, (255, 255, 255), (cx - 8, int(y_mouse), 16, int(y_ini - y_mouse)), 2)
        p.set_clip(None)

        pygame.draw.line(p, (255, 255, 255), (0, Y_CURSOR), (ANCHO, Y_CURSOR), 2)
        ahora = time.perf_counter()
        for i in range(CARRILES):
            relleno = 0 if (ahora - self.flash[i] < 0.12 or self.ctx.entrada.estado[i]) else 3
            pygame.draw.circle(p, COLORES[i], (i * ancho + ancho // 2, Y_CURSOR), 24, relleno)

        # Encabezado
        pygame.draw.rect(p, (20, 20, 30), (0, 0, ANCHO, HEADER))
        marca = " *" if (self.cambios or self.cambio_offset) else ""
        self.texto(f"{self.c['titulo']}{marca}  -  EDITOR", self.ctx.fuente, (255, 255, 255), 10, 8)
        t = self.c["offset"] + self.cursor * self.seg
        self.texto(f"Beat {self.cursor:.2f}   Tiempo {t:.2f}s   Precision 1/{self.div}   Notas {len(self.notas)}",
                   self.fuente_h, (200, 200, 220), 10, 42)
        self.texto(f"Offset {self.c['offset']:+.2f}s   Tick {'ON' if self.tick_on else 'OFF'}   "
                   f"{'REPRODUCIENDO' if self.sonando else 'detenido'}",
                   self.fuente_h, (255, 120, 120) if self.sonando else (170, 170, 190), 10, 64)
        if self.mensaje and ahora - self.t_mensaje < 3.0:
            self.texto(self.mensaje, self.fuente_h, (255, 220, 0), 300, 64)

        ayuda = [
            "Arriba/abajo/rueda: mover   RePag/AvPag: 4 beats   Inicio: principio",
            "A S D F G o clic: nota   Arrastrar: nota larga   Supr: borrar   1-4: precision",
            "Espacio: reproducir (en vivo, mantener tecla = nota larga)   +/-: zoom   , .: offset",
            "Ctrl+S: guardar   Ctrl+Z: deshacer   T: tick   ESC: detener / salir",
        ]
        for i, linea in enumerate(ayuda):
            self.texto(linea, self.fuente_h, (150, 150, 170), 8, Y_FIN + 8 + i * 22)
        pygame.display.flip()

    # ---------- bucle ----------
    def correr(self):
        ancho = ANCHO // CARRILES
        while True:
            self.ctx.reloj.tick(120)
            ahora = time.perf_counter()
            previo = self.cursor
            if self.sonando:
                self.cursor = self.cursor0 + (ahora - self.t_wall0) / self.seg
                if ahora - self.t_wall0 > 0.5 and not pygame.mixer.music.get_busy():
                    self.detener()
            pulsos = self.ctx.entrada.actualizar()

            ctrl_apretado = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.mixer.music.stop()
                    return "cerrar"
                if e.type == pygame.MOUSEWHEEL and not self.sonando:
                    self.mover(e.y * self.snap)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and not self.sonando:
                    x, y = e.pos
                    if HEADER <= y <= Y_FIN:
                        carril = min(CARRILES - 1, x // ancho)
                        beat = self.ajustar((Y_CURSOR - y) / self.ppb + self.cursor)
                        self.arrastre = (carril, beat)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.arrastre:
                    carril, ini = self.arrastre
                    self.arrastre = None
                    fin = self.ajustar((Y_CURSOR - e.pos[1]) / self.ppb + self.cursor)
                    if fin - ini >= self.snap - 1e-9:
                        self.poner_larga(ini, carril, fin - ini)   # arrastre = nota larga
                    else:
                        self.alternar(ini, carril)                 # clic simple = poner/quitar
                elif e.type == pygame.KEYDOWN:
                    ctrl = bool(e.mod & pygame.KMOD_CTRL)
                    ctrl_apretado = ctrl_apretado or ctrl
                    if e.key != pygame.K_ESCAPE:
                        self.confirmar_salida = False
                    if e.key == pygame.K_ESCAPE:
                        if self.sonando:
                            self.detener()
                        elif self.cambios and not self.confirmar_salida:
                            self.confirmar_salida = True
                            self.avisar("Sin guardar: ESC otra vez sale, Ctrl+S guarda")
                        else:
                            pygame.mixer.music.stop()
                            return None
                    elif ctrl and e.key == pygame.K_s:
                        self.guardar()
                    elif ctrl and e.key == pygame.K_z:
                        self.deshacer()
                    elif e.key == pygame.K_SPACE:
                        if self.sonando:
                            self.detener()
                        else:
                            self.iniciar()
                    elif e.key == pygame.K_UP and not self.sonando:
                        self.mover(self.snap)
                    elif e.key == pygame.K_DOWN and not self.sonando:
                        self.mover(-self.snap)
                    elif e.key == pygame.K_PAGEUP and not self.sonando:
                        self.mover(4)
                    elif e.key == pygame.K_PAGEDOWN and not self.sonando:
                        self.mover(-4)
                    elif e.key == pygame.K_HOME and not self.sonando:
                        self.cursor = 0.0
                    elif e.key in (pygame.K_1, pygame.K_KP1):
                        self.div = 1
                    elif e.key in (pygame.K_2, pygame.K_KP2):
                        self.div = 2
                    elif e.key in (pygame.K_3, pygame.K_KP3):
                        self.div = 4
                    elif e.key in (pygame.K_4, pygame.K_KP4):
                        self.div = 8
                    elif e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                        self.ppb = min(400.0, self.ppb * 1.25)
                    elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                        self.ppb = max(30.0, self.ppb / 1.25)
                    elif e.key == pygame.K_t:
                        self.tick_on = not self.tick_on
                    elif e.key == pygame.K_DELETE and not self.sonando:
                        self.borrar_beat()
                    elif e.key in (pygame.K_COMMA, pygame.K_PERIOD) and not self.sonando:
                        self.c["offset"] += -0.01 if e.key == pygame.K_COMMA else 0.01
                        self.cambio_offset = True

            # Notas con teclas / botones del Arduino (se ignoran con Ctrl apretado)
            if not (pygame.key.get_mods() & pygame.KMOD_CTRL) and not ctrl_apretado:
                for carril in pulsos:
                    beat = self.ajustar(self.cursor)
                    if self.sonando:
                        self.agregar(beat, carril)
                        self.vivo[carril] = self.cursor
                    else:
                        self.alternar(beat, carril)

            # En vivo: al soltar la tecla, si se mantuvo >= 1/2 beat la nota pasa a ser larga
            if self.sonando:
                for carril, inicio in list(self.vivo.items()):
                    if not self.ctx.entrada.estado[carril]:
                        self.cerrar_larga(carril, inicio)
                        del self.vivo[carril]

            # Tick y destello al pasar por las notas mientras suena
            if self.sonando and self.cursor > previo:
                for beat, carril, _dur in self.notas:
                    if previo < beat <= self.cursor:
                        self.flash[carril] = ahora
                        if self.tick_on and self.click:
                            self.click.play()

            self.dibujar()


def editar(ctx, cancion):
    """Abre el editor. Devuelve 'cerrar' si se cerro la ventana, o None."""
    return Editor(ctx, cancion).correr()