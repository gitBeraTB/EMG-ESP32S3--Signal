#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <math.h>

// ================================================================
//  ESP-NOW SETTINGS
// ================================================================
uint8_t receiverAddress[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

typedef struct struct_message {
  int gestureID;
  float confidence;
  int batteryLevel;
  uint32_t timestamp;
} struct_message;

struct_message myData;
esp_now_peer_info_t peerInfo;

void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  // Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Basarili" : "Hata");
}

// ================================================================
//  MOD SECIMI — Sadece birini aktif birak!
//  MODE_COLLECT   : Veri toplama (Serial'e CSV formatinda 3 kanal basar)
//  MODE_INFERENCE : Gercek zamanli tahmin
// ================================================================
// #define MODE_COLLECT
#define MODE_INFERENCE

#ifdef MODE_INFERENCE
#include "model.h"
// ---------------------------------------------------------------
//  ESP32‑S3 EMG REAL‑TIME INFERENCE (model.h ONLY)
// ---------------------------------------------------------------
Eloquent::ML::Port::RandomForest clf;
#endif

// -----------------------------------------------------------------
//  SETTINGS
// -----------------------------------------------------------------
const int EMG_PIN_1 = 4;           // ADC1_CH3  -> CH1 (cene/jaw)
const int EMG_PIN_2 = 5;           // ADC1_CH4  -> CH2 (bilek/wrist)
const int EMG_PIN_3 = 6;           // ADC1_CH5  -> CH3 (biceps/dirsek-elbow)
const int NUM_CH    = 3;           // aktif EMG kanal sayisi (CH1=cene, CH2=bilek, CH3=dirsek)
const int SAMPLING_RATE_HZ = 2000; // 2 kHz acquisition
const int64_t SAMPLE_PERIOD_US = 1000000 / SAMPLING_RATE_HZ;

// -----------------------------------------------------------------
//  50 Hz NOTCH FILTER (IIR, order‑2) - 2 Channels
// -----------------------------------------------------------------
const float NOTCH_FREQ = 50.0;
const float NOTCH_R = 0.95;
const float cosW0 = cos(2.0 * PI * NOTCH_FREQ / SAMPLING_RATE_HZ);
const float K0 =
    (1.0 - 2.0 * NOTCH_R * cosW0 + NOTCH_R * NOTCH_R) / (2.0 - 2.0 * cosW0);
const float b0 = K0;
const float b1 = -2.0 * K0 * cosW0;
const float b2 = K0;
const float a1 = -2.0 * NOTCH_R * cosW0;
const float a2 = NOTCH_R * NOTCH_R;

float x_prev1[NUM_CH] = {0}, x_prev2[NUM_CH] = {0};
float y_prev1[NUM_CH] = {0}, y_prev2[NUM_CH] = {0};

float applyNotchFilter(float x, int ch) {
  float y = b0 * x + b1 * x_prev1[ch] + b2 * x_prev2[ch] - a1 * y_prev1[ch] -
            a2 * y_prev2[ch];
  x_prev2[ch] = x_prev1[ch];
  x_prev1[ch] = x;
  y_prev2[ch] = y_prev1[ch];
  y_prev1[ch] = y;
  return y;
}

// -----------------------------------------------------------------
//  FIR LOW-PASS FILTER (10-tap Moving Average) - 2 Channels
// -----------------------------------------------------------------
const int FIR_TAPS = 10;
float fir_buffer[NUM_CH][FIR_TAPS] = {0};
int fir_idx[NUM_CH] = {0};

float applyFIRFilter(float x, int ch) {
  fir_buffer[ch][fir_idx[ch]] = x;
  fir_idx[ch] = (fir_idx[ch] + 1) % FIR_TAPS;

  float sum = 0;
  for (int i = 0; i < FIR_TAPS; ++i) {
    sum += fir_buffer[ch][i];
  }
  return sum / (float)FIR_TAPS;
}

// -----------------------------------------------------------------
//  QUEUE AND DATA STRUCTURE
// -----------------------------------------------------------------
QueueHandle_t emgQueue;
struct EMGData {
  uint16_t ch1;
  uint16_t ch2;
  uint16_t ch3;
};

// -----------------------------------------------------------------
//  ADC TASK
// -----------------------------------------------------------------
void adcTask(void *pvParameters) {
  EMGData data;
  int64_t nextSampleTime = esp_timer_get_time();
  float dc_offset[NUM_CH] = {2047.0, 2047.0, 2047.0};

  // quick DC calibration
  float sum[NUM_CH] = {0};
  for (int i = 0; i < 200; ++i) {
    sum[0] += analogRead(EMG_PIN_1);
    sum[1] += analogRead(EMG_PIN_2);
    sum[2] += analogRead(EMG_PIN_3);
    delayMicroseconds(500);
  }
  for (int ch = 0; ch < NUM_CH; ch++) {
    dc_offset[ch] = sum[ch] / 200.0;
    Serial.printf("[OK] Initial DC offset CH%d: %.2f\n", ch + 1, dc_offset[ch]);
  }

  for (;;) {
    uint16_t rawVals[NUM_CH];
    rawVals[0] = analogRead(EMG_PIN_1);
    rawVals[1] = analogRead(EMG_PIN_2);
    rawVals[2] = analogRead(EMG_PIN_3);

    uint16_t finalVals[NUM_CH];
    float SOFTWARE_GAIN = 5.0; // Sinyali 5 kat buyutur

    for (int ch = 0; ch < NUM_CH; ch++) {
      dc_offset[ch] = 0.999 * dc_offset[ch] + 0.001 * (float)rawVals[ch];
      float ac_val = (float)rawVals[ch] - dc_offset[ch];
      float filtered_ac = applyNotchFilter(ac_val, ch);
      float fir_ac = applyFIRFilter(filtered_ac, ch);

      // Gain (Kazanc) uygula ve merkeze oturt
      float final_val = (fir_ac * SOFTWARE_GAIN) + 2047.0;

      if (final_val < 0)
        final_val = 0;
      if (final_val > 4095)
        final_val = 4095;
      finalVals[ch] = (uint16_t)final_val;
    }

    data.ch1 = finalVals[0];
    data.ch2 = finalVals[1];
    data.ch3 = finalVals[2];
    xQueueSend(emgQueue, &data, 0);

    nextSampleTime += SAMPLE_PERIOD_US;
    int64_t now = esp_timer_get_time();
    if (nextSampleTime > now) {
      delayMicroseconds(nextSampleTime - now);
    }
  }
}

// -----------------------------------------------------------------
//  SERIAL TASK
// -----------------------------------------------------------------
const int WINDOW_SIZE = 50;
const int STEP_SIZE = 25;
float window_buffer[NUM_CH][WINDOW_SIZE];
int window_idx = 0;

void serialTask(void *pvParameters) {
  EMGData data;
  for (;;) {
    if (xQueueReceive(emgQueue, &data, portMAX_DELAY) == pdPASS) {
#ifdef MODE_COLLECT
      Serial.printf("%d,%d,%d\n", data.ch1, data.ch2, data.ch3);
#endif

#ifdef MODE_INFERENCE
      window_buffer[0][window_idx] = (float)data.ch1 * 3.3f / 4095.0f;
      window_buffer[1][window_idx] = (float)data.ch2 * 3.3f / 4095.0f;
      window_buffer[2][window_idx] = (float)data.ch3 * 3.3f / 4095.0f;
      window_idx++;

      if (window_idx >= WINDOW_SIZE) {
        float features[NUM_CH * 6]; // 3 channels * 6 features

        for (int ch = 0; ch < NUM_CH; ++ch) {
          float sum = 0, sum_sq = 0;
          float min_val = window_buffer[ch][0];
          float max_val = window_buffer[ch][0];

          for (int i = 0; i < WINDOW_SIZE; ++i) {
            float v = window_buffer[ch][i];
            sum += v;
            sum_sq += v * v;
            if (v < min_val)
              min_val = v;
            if (v > max_val)
              max_val = v;
          }
          float mean_val = sum / (float)WINDOW_SIZE;
          float rms_val = sqrt(sum_sq / (float)WINDOW_SIZE);

          float var_sum = 0;
          for (int i = 0; i < WINDOW_SIZE; ++i) {
            var_sum += (window_buffer[ch][i] - mean_val) *
                       (window_buffer[ch][i] - mean_val);
          }
          float var_val = var_sum / (float)WINDOW_SIZE;
          float std_val = sqrt(var_val);

          int f_idx = ch * 6;
          features[f_idx + 0] = mean_val;
          features[f_idx + 1] = std_val;
          features[f_idx + 2] = var_val;
          features[f_idx + 3] = rms_val;
          features[f_idx + 4] = min_val;
          features[f_idx + 5] = max_val;
        }

        // Her kanal kendi 6 feature blogu ile ayni REST/SQUEEZE modelinden gecer
        int pred_ch1 = clf.predict(&features[0]);  // CH1 -> cene   (jaw)
        int pred_ch2 = clf.predict(&features[6]);  // CH2 -> bilek  (wrist)
        int pred_ch3 = clf.predict(&features[12]); // CH3 -> dirsek (elbow/biceps)

        // UART paketi: [0xAA][ch1][ch2][ch3][0x55]
        uint8_t packet[5] = {0xAA, (uint8_t)pred_ch1, (uint8_t)pred_ch2,
                             (uint8_t)pred_ch3, 0x55};
        Serial1.write(packet, 5);

        // ESP-NOW paketi (gestureID alanina uc kanali paketle: ch1 | ch2<<1 | ch3<<2)
        myData.gestureID = (pred_ch1 & 0x01) | ((pred_ch2 & 0x01) << 1) |
                           ((pred_ch3 & 0x01) << 2);
        myData.confidence = 1.0;
        myData.batteryLevel = 95;
        myData.timestamp = millis();
        esp_now_send(receiverAddress, (uint8_t *)&myData, sizeof(myData));

        // Serial ciktisi (Okunabilir metin)
        Serial.printf("CH1(cene): %s | CH2(bilek): %s | CH3(dirsek): %s\n",
                      pred_ch1 ? "SQUEEZE" : "REST",
                      pred_ch2 ? "SQUEEZE" : "REST",
                      pred_ch3 ? "SQUEEZE" : "REST");

        // slide window
        for (int ch = 0; ch < NUM_CH; ++ch) {
          for (int i = 0; i < (WINDOW_SIZE - STEP_SIZE); ++i) {
            window_buffer[ch][i] = window_buffer[ch][i + STEP_SIZE];
          }
        }
        window_idx = WINDOW_SIZE - STEP_SIZE;
      }
#endif
    }
  }
}

// -----------------------------------------------------------------
//  SETUP & LOOP
// -----------------------------------------------------------------
void setup() {
  Serial.begin(921600);
  Serial1.begin(115200, SERIAL_8N1, 18, 17);
  delay(1000);

#ifdef MODE_COLLECT
  Serial.println("--- EMG VERI TOPLAMA MODU (3 Kanal) ---");
#endif
#ifdef MODE_INFERENCE
  Serial.println("--- EMG REAL-TIME INFERENCE 3CH (model.h) ---");
#endif

  analogSetAttenuation(ADC_11db);
  analogReadResolution(12);

  // --- ESP-NOW KURULUMU ---
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  if (esp_now_init() != ESP_OK) {
    Serial.println("[HATA] ESP-NOW baslatilamadi!");
  } else {
    esp_now_register_send_cb(OnDataSent);
    memcpy(peerInfo.peer_addr, receiverAddress, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
      Serial.println("[HATA] ESP-NOW Peer eklenemedi!");
    } else {
      Serial.println("[OK] ESP-NOW Baslatildi");
    }
  }

  emgQueue = xQueueCreate(200, sizeof(EMGData));
  if (emgQueue == NULL) {
    Serial.println("[HATA] Queue creation failed");
    return;
  }

  xTaskCreatePinnedToCore(adcTask, "ADC_Task", 4096, NULL, 2, NULL, 0);
  xTaskCreatePinnedToCore(serialTask, "Serial_Task", 8192, NULL, 1, NULL, 1);
  Serial.println("[OK] Tasks started");
}

void loop() { vTaskDelete(NULL); }