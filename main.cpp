#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <esp_timer.h>

// ==========================================
// --- AYARLAR ---
// ==========================================

// ⚠️ ESP32-S3 N8R16 ADC1 Geçerli Pinler: GPIO 1-10
// ⚠️ GPIO 33-37 dahili flash/PSRAM tarafından kullanılır, KULLANILAMAZ!
// 
// 4D Systems ESP32-S3 Gen4 boardunda hangi pinlerin dışarı çıktığı
// modele göre değişir. EMG sensörünü aşağıdaki pinlerden birine bağlayın.
// Başlangıçta TÜM ADC1 pinleri taranır, hangisinde sinyal varsa gösterilir.

const int EMG_PIN = 4;  // Varsayılan pin - ADC1_CH3 (ESP32-S3)

// Tarama için tüm ADC1 pinleri (başlangıç diagnostiğinde hepsi test edilir)
const int ADC1_PINS[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
const int NUM_ADC1_PINS = 10;

const int SAMPLING_RATE_HZ = 4000;
// 4000 Hz = 250 µs periyot (FreeRTOS tick 1ms olduğu için vTaskDelayUntil kullanılamaz)
const int64_t SAMPLE_PERIOD_US = 1000000 / SAMPLING_RATE_HZ; // 250 µs

// Görevler (Tasks) arası güvenli veri taşıma kuyruğu
QueueHandle_t emgQueue;

// Kuyrukta taşınacak veri yapısı
struct EMGData {
    uint16_t value;
};

// ==========================================
// --- 50 Hz NOTCH FİLTRE (Şebeke Gürültüsü Temizleme) ---
// ==========================================
// 2. derece IIR Notch Filtre - 50 Hz @ 4000 Hz örnekleme
// H(z) = (1 - 2cos(w0)z^-1 + z^-2) / (1 - 2r*cos(w0)z^-1 + r^2*z^-2)
// w0 = 2*PI*50/4000, r = 0.95 (dar çentik)

const float NOTCH_FREQ = 50.0;
const float NOTCH_R = 0.95; // Çentik genişliği (1'e yakın = daha dar)

// Ön-hesaplanmış katsayılar
const float cosW0 = cos(2.0 * PI * NOTCH_FREQ / SAMPLING_RATE_HZ); // ~0.99692
const float b0 = 1.0;
const float b1 = -2.0 * cosW0;          // ~ -1.99384
const float b2 = 1.0;
const float a1 = -2.0 * NOTCH_R * cosW0; // ~ -1.89415
const float a2 = NOTCH_R * NOTCH_R;      // ~ 0.9025

// Filtre bellek değişkenleri
float x_prev1 = 0, x_prev2 = 0; // Giriş geçmişi
float y_prev1 = 0, y_prev2 = 0; // Çıkış geçmişi

float applyNotchFilter(float x) {
    // IIR Direct Form I: y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
    float y = b0 * x + b1 * x_prev1 + b2 * x_prev2
                      - a1 * y_prev1 - a2 * y_prev2;
    
    // Bellekleri kaydır
    x_prev2 = x_prev1;
    x_prev1 = x;
    y_prev2 = y_prev1;
    y_prev1 = y;
    
    return y;
}

// ==========================================
// --- GÖREV 1: ADC OKUMA + FİLTRELEME (ÇEKİRDEK 0) ---
// ==========================================
void adcTask(void *pvParameters) {
    EMGData data;
    int64_t nextSampleTime = esp_timer_get_time();

    for (;;) {
        uint16_t rawVal = analogRead(EMG_PIN);
        
        // 50 Hz notch filtre uygula
        float filtered = applyNotchFilter((float)rawVal);
        
        // Filtrelenmiş değeri 0-4095 aralığına kırp
        if (filtered < 0) filtered = 0;
        if (filtered > 4095) filtered = 4095;
        data.value = (uint16_t)filtered;
        
        xQueueSend(emgQueue, &data, 0);

        // Mikrosaniye hassasiyetinde zamanlama (4000 Hz = 250 µs periyot)
        nextSampleTime += SAMPLE_PERIOD_US;
        int64_t now = esp_timer_get_time();
        if (nextSampleTime > now) {
            delayMicroseconds(nextSampleTime - now);
        }
    }
}

// ==========================================
// --- GÖREV 2: SERIAL YAZMA (ÇEKİRDEK 1) ---
// ==========================================
void serialTask(void *pvParameters) {
    EMGData data;
    
    for (;;) {
        if (xQueueReceive(emgQueue, &data, portMAX_DELAY) == pdPASS) {
            Serial.println(data.value);
        }
    }
}

// ==========================================
// --- ANA KURULUM ---
// ==========================================
void setup() {
    Serial.begin(115200);
    delay(1000); // Serial + USB CDC bağlantısının tamamen stabil olması için

    Serial.println();
    Serial.println("==========================================");
    Serial.println("  EMG Tek Kanal - ESP32-S3 N8R16");
    Serial.println("  4D Systems Gen4 Board");
    Serial.println("==========================================");

    // *** KRİTİK: ADC ATTENUATION AYARI ***
    // Varsayılan 0dB sadece 0-1.1V okur!
    // 11dB ayarı ile 0-3.3V aralığında okuma yapılır.
    analogSetAttenuation(ADC_11db);
    analogReadResolution(12); // 0-4095

    Serial.println("[OK] ADC Attenuation: 11dB (0-3.3V araligi)");
    Serial.println("[OK] ADC Resolution: 12-bit (0-4095)");
    Serial.println();

    // ==========================================
    // TÜM ADC1 PİNLERİNİ TARA (GPIO 1-10)
    // Hangi pinde sinyal var görelim
    // ==========================================
    Serial.println("--- TUM ADC1 PIN TARAMASI (GPIO 1-10) ---");
    Serial.println("Pin  |  Ham Deger  |  mV      |  Voltaj");
    Serial.println("-----|-------------|----------|--------");
    
    int bestPin = -1;
    int bestVal = 0;

    for (int i = 0; i < NUM_ADC1_PINS; i++) {
        int pin = ADC1_PINS[i];
        pinMode(pin, INPUT);
        delay(10);
        
        // 10 okuma yapıp ortalamasını al (gürültüyü azalt)
        long sum = 0;
        for (int j = 0; j < 10; j++) {
            sum += analogRead(pin);
            delayMicroseconds(500);
        }
        int avgVal = sum / 10;
        int mV = analogReadMilliVolts(pin);
        float voltage = mV / 1000.0;
        
        Serial.print("GPIO ");
        if (pin < 10) Serial.print(" ");
        Serial.print(pin);
        Serial.print(" |    ");
        Serial.print(avgVal);
        if (avgVal < 10) Serial.print("   ");
        else if (avgVal < 100) Serial.print("  ");
        else if (avgVal < 1000) Serial.print(" ");
        Serial.print("    |  ");
        Serial.print(mV);
        if (mV < 10) Serial.print("   ");
        else if (mV < 100) Serial.print("  ");
        else if (mV < 1000) Serial.print(" ");
        Serial.print("  mV |  ");
        Serial.print(voltage, 3);
        Serial.print(" V");
        
        // 50'den büyük okumalar "sinyal var" sayılır
        if (avgVal > 50) {
            Serial.print("  <-- SINYAL VAR!");
            if (avgVal > bestVal) {
                bestVal = avgVal;
                bestPin = pin;
            }
        }
        Serial.println();
    }
    
    Serial.println("-----|-------------|----------|--------");
    Serial.println();
    
    if (bestPin >= 0) {
        Serial.print("[!] En guclu sinyal: GPIO ");
        Serial.print(bestPin);
        Serial.print(" (deger: ");
        Serial.print(bestVal);
        Serial.println(")");
    } else {
        Serial.println("[UYARI] HICBIR PINDE SINYAL BULUNAMADI!");
        Serial.println("  -> EMG devresinin cikisini GPIO 1-10 pinlerinden birine baglayin");
        Serial.println("  -> EMG devresi ile ESP32 arasinda GND baglantisini kontrol edin");
        Serial.println("  -> EMG devresinin beslendiginden (guc aldiginddan) emin olun");
    }
    
    Serial.println();
    Serial.print("Kullanilan ADC pini: GPIO ");
    Serial.println(EMG_PIN);
    
    // Seçili pini tekrar test et
    Serial.println();
    Serial.println("--- SECILI PIN DETAYLI TEST (5 okuma) ---");
    for (int i = 0; i < 5; i++) {
        uint16_t raw = analogRead(EMG_PIN);
        int mV = analogReadMilliVolts(EMG_PIN);
        Serial.print("  #");
        Serial.print(i + 1);
        Serial.print(":  Raw=");
        Serial.print(raw);
        Serial.print("  mV=");
        Serial.print(mV);
        Serial.print("  V=");
        Serial.println(mV / 1000.0, 3);
        delay(200);
    }

    Serial.println();
    Serial.println("--- VERI AKISI BASLIYOR ---");

    // 20 kapasiteli bir kuyruk oluştur
    emgQueue = xQueueCreate(200, sizeof(EMGData));

    if (emgQueue != NULL) {
        xTaskCreatePinnedToCore(
            adcTask,
            "ADC_Task",
            2048,
            NULL,
            2,
            NULL,
            0
        );

        xTaskCreatePinnedToCore(
            serialTask,
            "Serial_Task",
            4096,
            NULL,
            1,
            NULL,
            1
        );
        Serial.println("[OK] RTOS gorevleri baslatildi.");
    } else {
        Serial.println("[HATA] Kuyruk olusturulamadi!");
    }
}

void loop() {
    vTaskDelete(NULL);
}