// 4 botones (INPUT_PULLUP) + 4 LEDs. Manda "1001\n" por serial cuando cambia algo.
// El LED de cada carril se enciende mientras apretas su boton.

const int N = 4;                           // cantidad de botones (tiene que coincidir con config.py)
const int BOTONES[N] = {2, 3, 4, 5};       // boton entre el pin y GND
const int LEDS[N]    = {8, 9, 10, 11};     // pin -> resistencia 220 ohm -> LED (pata larga) -> GND

char anterior[N + 1] = "0000";

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < N; i++) {
    pinMode(BOTONES[i], INPUT_PULLUP);
    pinMode(LEDS[i], OUTPUT);
  }
}

void loop() {
  char actual[N + 1];
  for (int i = 0; i < N; i++) {
    bool apretado = (digitalRead(BOTONES[i]) == LOW); // con pullup, LOW = apretado
    actual[i] = apretado ? '1' : '0';
    digitalWrite(LEDS[i], apretado ? HIGH : LOW);
  }
  actual[N] = '\0';

  if (strcmp(actual, anterior) != 0) {
    Serial.println(actual);
    strcpy(anterior, actual);
  }
  delay(2); // antirrebote simple
}
