#include <Adafruit_NeoPixel.h>

#define NUM_STRIPS     4
#define LEDS_POR_TIRA  18
#define BRILLO         100

const uint8_t BOTONES[NUM_STRIPS] = {2, 3, 4, 5};
const uint8_t PINES[NUM_STRIPS]   = {8, 9, 10, 11};

const uint32_t COLOR_APAGADO = Adafruit_NeoPixel::Color(0, 0, 0);
const uint32_t COLOR_NOTA    = Adafruit_NeoPixel::Color(0, 150, 255); // Celeste
const uint32_t COLOR_GOLPE   = Adafruit_NeoPixel::Color(0, 255, 0);   // Verde

Adafruit_NeoPixel tiras[NUM_STRIPS] = {
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[0], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[1], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[2], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(LEDS_POR_TIRA, PINES[3], NEO_GRB + NEO_KHZ800)
};

char anterior[NUM_STRIPS + 1] = "0000";
String buffer = "";

void setup() {
  Serial.begin(9600);
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
  // Formato esperado: L + carril (0-3) + 18 caracteres de color
  // 0 = apagado, 1 = celeste (nota), 2 = violeta (cola), 3 = verde (golpe)
  if (cmd.length() < 1 + 1 + LEDS_POR_TIRA) return;
  if (cmd[0] != 'L') return;

  int carril = cmd[1] - '0';
  if (carril < 0 || carril >= NUM_STRIPS) return;

  for (int i = 0; i < LEDS_POR_TIRA; i++) {
    char estado = cmd[2 + i];
    if (estado == '1') {
      tiras[carril].setPixelColor(i, COLOR_NOTA);      // Celeste
    } else if (estado == '2') {
      // Un violeta lindo para la cola
      tiras[carril].setPixelColor(i, Adafruit_NeoPixel::Color(150, 0, 255));
    } else if (estado == '3') {
      tiras[carril].setPixelColor(i, COLOR_GOLPE);     // Verde
    } else {
      tiras[carril].setPixelColor(i, COLOR_APAGADO);   // Apagado
    }
  }
  tiras[carril].show();
}