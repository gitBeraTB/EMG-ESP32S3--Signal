#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <esp_timer.h>
#include <math.h>
#include <esp_now.h>
#include <WiFi.h>

// ================================================================
//  MOD SECIMI — Sadece birini aktif birak!
//  MODE_COLLECT   : Veri toplama (Serial'e 3 kanal ham veri basar)
//  MODE_INFERENCE : Gercek zamanli tahmin + ESP-NOW gonderim
// ================================================================
#define MODE_COLLECT
// #define MODE_INFERENCE

// ================================================================
//  HAREKET SINIFLARI
//    0 = REST         (kol gevsek)
//    1 = ELBOW        (dirsek bukme / acma)
//    2 = SQUEEZE      (nesne sikma / birakma)
//    3 = POWER_GRIP   (guclu kavrama)
// ================================================================

// ================================================================
//  PIN ATAMASI — 3 ANALOG KANAL
// ================================================================
const int EMG_PIN_CH1 = 4;   // Biceps          — ADC1_CH3
const int EMG_PIN_CH2 = 5;   // On Kol Ic       — ADC1_CH4
const int EMG_PIN_CH3 = 6;   // On Kol Dis      — ADC1_CH5
const int NUM_CHANNELS = 3;
const int EMG_PINS[NUM_CHANNELS] = {EMG_PIN_CH1, EMG_PIN_CH2, EMG_PIN_CH3};

// ================================================================
//  ORNEKLEME
// ================================================================
const int SAMPLING_RATE_HZ    = 2000;
const int64_t SAMPLE_PERIOD_US = 1000000 / SAMPLING_RATE_HZ;

// ================================================================
//  50 Hz NOTCH FILTER (IIR, order-2) — kanal basina bagimsiz state
// ================================================================
const float NOTCH_FREQ = 50.0;
const float NOTCH_R    = 0.95;
const float cosW0 = cos(2.0 * PI * NOTCH_FREQ / SAMPLING_RATE_HZ);
const float K0 = (1.0 - 2.0 * NOTCH_R * cosW0 + NOTCH_R * NOTCH_R)
               / (2.0 - 2.0 * cosW0);
const float b0_n =  K0;
const float b1_n = -2.0 * K0 * cosW0;
const float b2_n =  K0;
const float a1_n = -2.0 * NOTCH_R * cosW0;
const float a2_n =  NOTCH_R * NOTCH_R;

// Her kanal icin bagimsiz filtre durumu
struct NotchState {
    float x1 = 0, x2 = 0;   // input history
    float y1 = 0, y2 = 0;   // output history
};
NotchState notch[NUM_CHANNELS];

float applyNotchFilter(float x, NotchState &s) {
    float y = b0_n * x + b1_n * s.x1 + b2_n * s.x2
                       - a1_n * s.y1 - a2_n * s.y2;
    s.x2 = s.x1;  s.x1 = x;
    s.y2 = s.y1;  s.y1 = y;
    return y;
}

// ================================================================
//  QUEUE VE VERI YAPISI — 3 KANAL
// ================================================================
QueueHandle_t emgQueue;
struct EMGData {
    uint16_t ch[NUM_CHANNELS];   // filtrelenmis ADC degerleri
};

// ================================================================
//  ESP-NOW YAPILANDIRMASI
// ================================================================
// Alici MAC adresi — sonradan degistirilecek
uint8_t receiverAddress[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

typedef struct struct_message {
    int   gestureID;       // 0=REST, 1=ELBOW, 2=SQUEEZE, 3=POWER_GRIP
    float confidence;      // model guven skoru (mock)
    int   batteryLevel;    // batarya %
} struct_message;

struct_message txData;
esp_now_peer_info_t peerInfo;

void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
    // Yuksek frekansta cagrilir — Serial baskisi kapatildi
    // Serial.println(status == ESP_NOW_SEND_SUCCESS ? "OK" : "FAIL");
}

// ================================================================
//  MODEL (sadece INFERENCE modunda kullanilir)
// ================================================================
#ifdef MODE_INFERENCE
#include "model.h"
Eloquent::ML::Port::RandomForest clf;
#endif

// ================================================================
//  DC OFFSET — kanal basina
// ================================================================
float dc_offset[NUM_CHANNELS];

// ================================================================
//  ADC TASK — Core 0, Priority 2
//  3 kanali 2 kHz'de okur, DC cikarir, notch uygular, queue'ya yazar
// ================================================================
void adcTask(void *pvParameters) {
    EMGData data;
    int64_t nextSampleTime = esp_timer_get_time();

    // Baslangic DC kalibrasyonu (her kanal icin 200 ornek)
    for (int c = 0; c < NUM_CHANNELS; c++) {
        float sum = 0;
        for (int i = 0; i < 200; i++) {
            sum += analogRead(EMG_PINS[c]);
            delayMicroseconds(250);
        }
        dc_offset[c] = sum / 200.0;
        Serial.printf("[OK] CH%d DC offset: %.1f\n", c + 1, dc_offset[c]);
    }

    for (;;) {
        for (int c = 0; c < NUM_CHANNELS; c++) {
            uint16_t rawVal = analogRead(EMG_PINS[c]);

            // Ultra-yavas DC takip (high-pass)
            dc_offset[c] = 0.999f * dc_offset[c] + 0.001f * (float)rawVal;

            // AC bilesen
            float ac_val = (float)rawVal - dc_offset[c];

            // Notch filtre
            float filtered_ac = applyNotchFilter(ac_val, notch[c]);

            // Merkeze geri getir
            float final_val = filtered_ac + 2047.0f;
            if (final_val < 0)    final_val = 0;
            if (final_val > 4095) final_val = 4095;

            data.ch[c] = (uint16_t)final_val;
        }

        xQueueSend(emgQueue, &data, 0);

        // 2 kHz zamanlama
        nextSampleTime += SAMPLE_PERIOD_US;
        int64_t now = esp_timer_get_time();
        if (nextSampleTime > now) {
            delayMicroseconds(nextSampleTime - now);
        }
    }
}

// ================================================================
//  SLIDING WINDOW — 3 KANAL
// ================================================================
const int WINDOW_SIZE = 50;   // ~25 ms @ 2 kHz
const int STEP_SIZE   = 25;   // %50 overlap
const int NUM_FEATURES_PER_CH = 6;
const int TOTAL_FEATURES = NUM_CHANNELS * NUM_FEATURES_PER_CH; // 18

float window_buf[NUM_CHANNELS][WINDOW_SIZE];
int   window_idx = 0;

// ================================================================
//  PROCESSING TASK — Core 1, Priority 1
//  Collect modunda Serial'e ham veri basar
//  Inference modunda feature extraction + model + ESP-NOW
// ================================================================
void processingTask(void *pvParameters) {
    EMGData data;
    // Serial cikti hiz kontrolu (collect modunda her ornegi basmaz, thinning)
    int sampleCounter = 0;

    for (;;) {
        if (xQueueReceive(emgQueue, &data, portMAX_DELAY) != pdPASS) continue;

#ifdef MODE_COLLECT
        // ----- VERI TOPLAMA MODU -----
        // Her ornegi Serial'e bas (Python tarafinda kaydedilir)
        // Format: CH1,CH2,CH3
        sampleCounter++;
        // 2000 Hz veriyi Serial'e basmak zor, her ornegi basiyoruz
        // cunku Python tarafinda kayit + grafik var
        Serial.printf("%u,%u,%u\n", data.ch[0], data.ch[1], data.ch[2]);
#endif

#ifdef MODE_INFERENCE
        // ----- TAHMIN MODU -----
        // Window'a ekle (ADC -> Volt)
        for (int c = 0; c < NUM_CHANNELS; c++) {
            window_buf[c][window_idx] = (float)data.ch[c] * 3.3f / 4095.0f;
        }
        window_idx++;

        if (window_idx >= WINDOW_SIZE) {
            // Feature extraction — her kanal icin 6 feature
            float features[TOTAL_FEATURES];
            int fi = 0;

            for (int c = 0; c < NUM_CHANNELS; c++) {
                float sum = 0, sum_sq = 0;
                float mn = window_buf[c][0];
                float mx = window_buf[c][0];

                for (int i = 0; i < WINDOW_SIZE; i++) {
                    float v = window_buf[c][i];
                    sum    += v;
                    sum_sq += v * v;
                    if (v < mn) mn = v;
                    if (v > mx) mx = v;
                }

                float mean_v = sum / (float)WINDOW_SIZE;
                float rms_v  = sqrtf(sum_sq / (float)WINDOW_SIZE);

                float var_sum = 0;
                for (int i = 0; i < WINDOW_SIZE; i++) {
                    float d = window_buf[c][i] - mean_v;
                    var_sum += d * d;
                }
                float var_v = var_sum / (float)WINDOW_SIZE;
                float std_v = sqrtf(var_v);

                // Siralama: mean, std, var, rms, min, max  (Colab ile ayni!)
                features[fi++] = mean_v;
                features[fi++] = std_v;
                features[fi++] = var_v;
                features[fi++] = rms_v;
                features[fi++] = mn;
                features[fi++] = mx;
            }

            // Model inference
            int prediction = clf.predict(features);

            // ESP-NOW gonderim
            txData.gestureID    = prediction;
            txData.confidence   = 0.99f;   // mock — model confidence yok
            txData.batteryLevel = 95;
            esp_err_t result = esp_now_send(receiverAddress,
                                            (uint8_t *)&txData, sizeof(txData));

            // Serial cikti
            Serial.printf("Raw:%u,%u,%u, Prediction:%d",
                          data.ch[0], data.ch[1], data.ch[2],
                          prediction * 1000);
            if      (prediction == 0) Serial.print(" // REST");
            else if (prediction == 1) Serial.print(" // ELBOW");
            else if (prediction == 2) Serial.print(" // SQUEEZE");
            else if (prediction == 3) Serial.print(" // POWER_GRIP");
            if (result != ESP_OK)     Serial.print(" [ESP-NOW HATA]");
            Serial.println();

            // Window kaydir (slide)
            for (int c = 0; c < NUM_CHANNELS; c++) {
                for (int i = 0; i < (WINDOW_SIZE - STEP_SIZE); i++) {
                    window_buf[c][i] = window_buf[c][i + STEP_SIZE];
                }
            }
            window_idx = WINDOW_SIZE - STEP_SIZE;
        }
#endif
    }
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

#ifdef MODE_COLLECT
    Serial.println("\n--- 3-KANAL EMG VERI TOPLAMA MODU ---");
#endif
#ifdef MODE_INFERENCE
    Serial.println("\n--- 3-KANAL EMG TAHMIN & ESP-NOW MODU ---");
#endif

    // ----- ESP-NOW Kurulumu -----
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    if (esp_now_init() != ESP_OK) {
        Serial.println("[HATA] ESP-NOW baslatilamadi!");
        return;
    }
    esp_now_register_send_cb(OnDataSent);
    memcpy(peerInfo.peer_addr, receiverAddress, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
        Serial.println("[HATA] ESP-NOW peer eklenemedi!");
        return;
    }
    Serial.println("[OK] ESP-NOW hazir.");

    // ----- ADC Ayarlari -----
    analogSetAttenuation(ADC_11db);   // 0-3.3 V
    analogReadResolution(12);         // 0-4095

    // ----- Queue -----
    emgQueue = xQueueCreate(256, sizeof(EMGData));
    if (emgQueue == NULL) {
        Serial.println("[HATA] Queue olusturulamadi!");
        return;
    }

    // ----- RTOS Tasks -----
    xTaskCreatePinnedToCore(adcTask,        "ADC_Task",   4096, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(processingTask, "Proc_Task",  8192, NULL, 1, NULL, 1);
    Serial.println("[OK] Gorevler baslatildi.");

    Serial.println("Kanal Pinleri:");
    Serial.printf("  CH1 (Biceps)     : GPIO %d\n", EMG_PIN_CH1);
    Serial.printf("  CH2 (On Kol Ic)  : GPIO %d\n", EMG_PIN_CH2);
    Serial.printf("  CH3 (On Kol Dis) : GPIO %d\n", EMG_PIN_CH3);
}

void loop() {
    // FreeRTOS gorevleri bagimsiz calisir
    vTaskDelete(NULL);
}
