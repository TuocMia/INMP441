#include <Arduino.h>
#include <WiFi.h>

#include "AudioTools.h"

using namespace audio_tools;

namespace {
constexpr const char *kWifiSsid = "TP-LINK_B9D2";
constexpr const char *kWifiPassword = "21377570";
constexpr const char *kRecorderHost = "192.168.0.106";
constexpr uint16_t kRecorderPort = 5000;

constexpr int kPinI2sBck = 14;
constexpr int kPinI2sWs = 15;
constexpr int kPinI2sSd = 32;
constexpr int kPinBoot = 0;  // BOOT button on GPIO0

const AudioInfo kMicInfo(16000, 1, 32);
const AudioInfo kPcmInfo(16000, 1, 16);

I2SStream mic;
WiFiClient client;
FormatConverterStream converter(mic);
StreamCopy copier(8192);

bool audioStarted = false;
bool isRecording = false;
unsigned long lastButtonPressTime = 0;
const unsigned long buttonDebounceDelay = 50;  // 50ms debounce (rút ngắn)
bool lastButtonState = HIGH;

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
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
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;  // INMP441 L/R tied to GND -> left channel
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

  if (!converter.begin(kMicInfo, kPcmInfo)) {
    Serial.println("Failed to start format converter");
    return false;
  }

  audioStarted = true;
  return true;
}

bool connectRecorder() {
  if (client.connected()) {
    return true;
  }

  client.stop();
  if (!client.connect(kRecorderHost, kRecorderPort)) {
    Serial.print("Could not connect to recorder server ");
    Serial.print(kRecorderHost);
    Serial.print(":");
    Serial.println(kRecorderPort);
    return false;
  }

  client.setNoDelay(false);

  copier.begin(client, converter);
  Serial.println("Recorder connected");
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
        Serial.println("Recording STARTED");
      } else {
        Serial.println("Recording STOPPED");
        if (client.connected()) {
          client.stop();
        }
      }
    }
  }
  lastButtonState = currentButtonState;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  AudioToolsLogger.begin(Serial, AudioToolsLogLevel::Warning);
  
  pinMode(kPinBoot, INPUT);  // Initialize BOOT button pin

  if (!connectWiFi()) {
    return;
  }

  if (!startAudioPipeline()) {
    return;
  }

  Serial.println("Press BOOT button to start/stop recording");
}

void loop() {
  checkBootButton();  // Check if BOOT button is pressed
  
  if (!connectWiFi()) {
    delay(100);
    return;
  }

  if (!audioStarted && !startAudioPipeline()) {
    delay(100);
    return;
  }

  if (isRecording) {
    if (!client.connected()) {
      if (!connectRecorder()) {
        delay(100);
        return;
      }
    }
    copier.copy();
  } else {
    if (client.connected()) {
      client.stop();
    }
  }
}