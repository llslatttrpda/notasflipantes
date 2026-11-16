"""Configuracion compartida por main.py y editor.py.

CARRILES: cantidad de notas/botones (4 con el controlador actual).
Si algun dia vuelven a ser 5, solo hay que cambiar este numero
(y el sketch del Arduino).
"""
CARRILES = 4

_COLORES_BASE = [(0, 200, 0), (220, 0, 0), (240, 220, 0), (0, 120, 255), (255, 140, 0)]
COLORES = _COLORES_BASE[:CARRILES]
