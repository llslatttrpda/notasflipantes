#include <Adafruit_NeoPixel.h>

// ================== CONFIGURACIÓN ==================
#define NUM_STRIPS     4
#define LEDS_POR_TIRA  50      // <-- AHORA SON 50 LEDS
#define BRILLO         100     

const uint8_t BOTONES[NUM_STRIPS] = {2, 3, 4, 5};
const uint8_t PINES[NUM_STRIPS]   = {8, 9, 10, 11};

// Colores
const uint32_t COLOR_NOTA    = Adafruit_NeoPixel::Color(0, 150, 255); // Celeste
const uint32_t COLOR_GOLPE   = Adafruit_NeoPixel::Color(0, 255, 0);   // Verde

Adafruit_NeoPixel tiras[NUM_STRIPS] = {
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[0], NEO_RGB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[1], NEO_RGB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[2], NEO_RGB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[3], NEO_RGB + NEO_KHZ800)
};

char anterior[NUM_STRIPS + 1] = "0000";
String buffer = "";

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < NUM_STRIPS; i++) {
    pinMode(BOTONES[i], INPUT_PULLUP);
    tiras[i].begin();
    tiras[i].setBrightness(BRILLO);
    tiras[i].clear();
    tiras[i].show();
  }
}

void loop() {
  // 1. Botones
  char actual[NUM_STRIPS + 1];
  for (int i = 0; i < NUM_STRIPS; i++) {
    actual[i] = (digitalRead(BOTONES[i]) == LOW) ? '1' : '0';
  }
  actual[NUM_STRIPS] = '\0';
  
  if (strcmp(actual, anterior) != 0) {
    Serial.println(actual);
    strcpy(anterior, actual);
  }

  // 2. Leer comandos de Python
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buffer.length() > 0) {
        procesarComando(buffer);
        buffer = "";
      }
    } else {
      buffer += c;
    }
  }
}

void procesarComando(String cmd) {
  if (cmd.length() < 1 + 1 + LEDS_POR_TIRA) return;
  if (cmd[0] != 'L') return;

  int carril = cmd[1] - '0';
  if (carril < 0 || carril >= NUM_STRIPS) return;

  for (int i = 0; i < LEDS_POR_TIRA; i++) {
    char estado = cmd[2 + i];
    uint32_t color = Adafruit_NeoPixel::Color(0, 0, 0); // Apagado por defecto
    
    if (estado == '1') color = COLOR_NOTA;      // Celeste (Nota)
    else if (estado == '2') color = Adafruit_NeoPixel::Color(150, 0, 255); // Violeta (Cola)
    else if (estado == '3') color = COLOR_GOLPE;     // Verde (Zona de golpe)
    else if (estado == '4') color = Adafruit_NeoPixel::Color(255, 0, 0);   // Rojo (Apretado)
    else if (estado == '5') color = Adafruit_NeoPixel::Color(255, 255, 0); // Amarillo (Transición)
    else if (estado == '6') color = Adafruit_NeoPixel::Color(255, 100, 0); // Naranja (Transición)

    tiras[carril].setPixelColor(i, color); 
  }
  tiras[carril].show();
} 