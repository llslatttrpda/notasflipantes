# Cómo jugar

Primero instalá lo necesario:

    pip install -r requirements.txt

Y después:

    python main.py

## Controles

En el menú, con las flechas elegís la canción y con Enter arrancás.
Si no tenés el Arduino enchufado, jugás con el teclado: A S D F G son los
5 botones, uno por carril.

Las notas caen y apretás el botón cuando la bolita llega al círculo de abajo.
Si le errás se corta el combo. Las que tienen cola hay que mantenerlas
apretadas hasta que termina la cola.

Si las notas se ven adelantadas o atrasadas respecto a la música, apretá
flecha izq/der mientras jugás para ajustar el offset (se guarda solo).

ESC corta la canción y te devuelve al menú.

## Agregar canciones

Adentro de `canciones/` hacé una carpeta por canción con el audio
(mp3, ogg o wav) y un `info.json` así:

    {
      "titulo": "Mi cancion",
      "artista": "Alguien",
      "bpm": 120
    }

Sin `chart.txt` el juego crea un chart de prueba solo. Para grabarlo de
verdad, elegí la canción en el menú, apretá R y tocale las notas siguiendo
la canción. Al apretar ESC se guarda.

Para editar las notas a mano apretá E en el menú y se abre el editor
(arriba está la lista de teclas).

## Charts de internet

Hay una comunidad enorme de charts listos para Clone Hero. El buscador es
https://www.enchor.us (chorus.encore.website era el de antes y anda caído;
también en r/CloneHero hay packs).

Lo mejor: descargás el chart, descomprimís la carpeta tal cual adentro de
`canciones/` y listo. Cuando abrís el juego, él solo convierte el
`notes.chart` (o `notes.mid`), crea el `info.json` con lo que hay en el `song.ini` y la
canción aparece en el menú.

Si querés otra dificultad (por defecto usa Expert guitar) ahí sí corré
el conversor a mano:

    python convertir_chart.py x --dificultad Medium

El `x` va porque pide algún argumento, da igual qué le pongas. Con
`--instrumento DoubleBass` convertís el bajo. Ojo que si tocás el
chart.txt a mano, para volver a convertir primero borralo (si no, el juego
no lo toca).

Si el chart trae las pistas separadas (guitar, bass, drums...) el juego las mezcla
solo en un mezcla.wav la primera vez (tarda unos segundos) y suena la canción completa.

Si las notas se van atrasando de a poco hacia el final de la canción, es
que el bpm del info.json no es exacto.

## Arduino

El juego busca el puerto COM3 a 9600 baudios (está en `PUERTO` y `BAUDIOS`
al principio de `main.py` si usás otro). La placa tiene que mandar una
línea con 5 números, un 1 por cada botón apretado, ej: `00100`.
