#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "AudioTools.h"

using namespace audio_tools;

namespace {
constexpr const char *kWifiSsid = "TP-LINK_B9D2";
constexpr const char *kWifiPassword = "21377570";
constexpr const char *kRecorderHost = "192.168.0.102";
constexpr uint16_t kRecorderPort = 5000;
constexpr uint16_t kUdpLocalPort = 5001;

constexpr int kPinI2sBck = 14;
constexpr int kPinI2sWs = 15;
constexpr int kPinI2sSd = 32;
constexpr int kPinBoot = 0;  // BOOT button on GPIO0

const AudioInfo kMicInfo(16000, 2, 32);
const AudioInfo kMicMonoInfo(16000, 1, 32);
const AudioInfo kPcmInfo(16000, 1, 16);
constexpr float kAudioGain = 0.5f;
constexpr size_t kFrameMs = 20;
constexpr size_t kPcmPayloadBytes = 640;  // 16kHz * 1ch * 16bit * 20ms

I2SStream mic;
WiFiUDP udp;
ChannelFormatConverterStream channelConverter(mic);
NumberFormatConverterStream numberConverter(channelConverter);

bool audioStarted = false;
volatile bool isRecording = false;
volatile bool wifiReady = false;
bool udpStarted = false;
uint32_t packetSequence = 0;
unsigned long lastButtonPressTime = 0;
const unsigned long buttonDebounceDelay = 50;  // 50ms debounce (rút ngắn)
bool lastButtonState = HIGH;

TaskHandle_t controlTaskHandle = nullptr;
TaskHandle_t audioTaskHandle = nullptr;

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(kWifiSsid, kWifiPassword);

  Serial.print("Connecting WiFi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
    if (millis() - start > 20000) {
      Serial.println();
      Serial.println("WiFi connect timeout");
      return false;
    }
  }

  Serial.println();
  Serial.print("WiFi connected, IP: ");
  Serial.println(WiFi.localIP());
  WiFi.setSleep(false);
  return true;
}

bool startAudioPipeline() {
  if (audioStarted) {
    return true;
  }

  auto cfg = mic.defaultConfig(RX_MODE);
  cfg.sample_rate = kMicInfo.sample_rate;
  cfg.channels = kMicInfo.channels;
  cfg.bits_per_sample = 32;  // INMP441 outputs in 32-bit I2S slots
#if defined(I2S_CHANNEL_FMT_ONLY_LEFT)
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;  // INMP441 L/R tied to GND -> left channel
#elif defined(I2S_CHANNEL_FMT_ALL_LEFT)
  cfg.channel_format = I2S_CHANNEL_FMT_ALL_LEFT;
#endif
  cfg.i2s_format = I2S_STD_FORMAT;
  cfg.is_master = true;
  cfg.pin_bck = kPinI2sBck;
  cfg.pin_ws = kPinI2sWs;
  cfg.pin_data = kPinI2sSd;
  cfg.buffer_count = 16;
  cfg.buffer_size = 1024;
  cfg.use_apll = false;

  if (!mic.begin(cfg)) {
    Serial.println("Failed to start I2S microphone");
    return false;
  }

  if (!channelConverter.begin(kMicInfo, kMicMonoInfo)) {
    Serial.println("Failed to start channel converter");
    return false;
  }

  if (!numberConverter.begin(kMicMonoInfo, kPcmInfo.bits_per_sample, kAudioGain)) {
    Serial.println("Failed to start number converter");
    return false;
  }

  audioStarted = true;
  return true;
}

bool startUdp() {
  if (udpStarted) {
    return true;
  }

  if (!udp.begin(kUdpLocalPort)) {
    Serial.println("Failed to start UDP");
    return false;
  }

  udpStarted = true;
  Serial.println("UDP transport ready");
  return true;
}

void checkBootButton() {
  // Boot button (GPIO0) is LOW when pressed
  bool currentButtonState = digitalRead(kPinBoot);
  
  // Detect button press (HIGH to LOW transition)
  if (lastButtonState == HIGH && currentButtonState == LOW) {
    unsigned long currentTime = millis();
    if (currentTime - lastButtonPressTime > buttonDebounceDelay) {
      lastButtonPressTime = currentTime;
      isRecording = !isRecording;
      
      if (isRecording) {
        packetSequence = 0;
        Serial.println("Recording STARTED");
      } else {
        Serial.println("Recording STOPPED");
      }
    }
  }
  lastButtonState = currentButtonState;
}

void controlTask(void *parameter) {
  (void)parameter;
  unsigned long lastWifiAttemptTime = 0;

  for (;;) {
    checkBootButton();

    if (WiFi.status() == WL_CONNECTED) {
      wifiReady = true;
    } else {
      wifiReady = false;
      unsigned long now = millis();
      if (now - lastWifiAttemptTime >= 1000) {
        lastWifiAttemptTime = now;
        connectWiFi();
      }
    }

    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void audioTask(void *parameter) {
  (void)parameter;
  static uint8_t pcmBuffer[kPcmPayloadBytes];
  static uint8_t packetBuffer[4 + kPcmPayloadBytes];

  for (;;) {
    if (!audioStarted && !startAudioPipeline()) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    if (!udpStarted && !startUdp()) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    if (!isRecording) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }

    if (!wifiReady) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }

    size_t pcmRead = numberConverter.readBytes(pcmBuffer, sizeof(pcmBuffer));
    if (pcmRead == 0) {
      vTaskDelay(pdMS_TO_TICKS(1));
      continue;
    }

    packetBuffer[0] = static_cast<uint8_t>(packetSequence & 0xFF);
    packetBuffer[1] = static_cast<uint8_t>((packetSequence >> 8) & 0xFF);
    packetBuffer[2] = static_cast<uint8_t>((packetSequence >> 16) & 0xFF);
    packetBuffer[3] = static_cast<uint8_t>((packetSequence >> 24) & 0xFF);
    memcpy(packetBuffer + 4, pcmBuffer, pcmRead);

    if (udp.beginPacket(kRecorderHost, kRecorderPort)) {
      udp.write(packetBuffer, 4 + pcmRead);
      udp.endPacket();
      ++packetSequence;
    }

    taskYIELD();
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  AudioToolsLogger.begin(Serial, AudioToolsLogLevel::Warning);
  
  pinMode(kPinBoot, INPUT_PULLUP);  // BOOT button is active LOW

  if (!connectWiFi()) {
    Serial.println("WiFi not ready at boot, retrying in control task");
  } else {
    wifiReady = true;
  }

  if (!startAudioPipeline()) {
    Serial.println("Audio pipeline not ready at boot, retrying in audio task");
  }

  Serial.println("Press BOOT button to start/stop recording");

  xTaskCreatePinnedToCore(controlTask, "control-task", 4096, nullptr, 2,
                          &controlTaskHandle, 1);
  xTaskCreatePinnedToCore(audioTask, "audio-task", 8192, nullptr, 3,
                          &audioTaskHandle, 0);
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}