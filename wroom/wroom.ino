#include <CAN.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "esp_task_wdt.h"
#include <ESP32Time.h>
#include <Update.h>

#define LED_BRIGHTNESS 0.3
#define UPDATE_BUFFER_SIZE 1024

typedef struct data{
    uint32_t id;
    uint32_t ts;
    uint32_t us;
    uint8_t d[8];
} msg_t;


struct color{
    uint8_t r=0;
    uint8_t g=0;
    uint8_t b=0;
};

struct color red;
struct color blue;
struct color green;
struct color yellow;
struct color cyan;

msg_t *buffer1;
msg_t *buffer2;
msg_t *buffer;

uint32_t *filtered_msg_ids = NULL;

uint16_t buffer_index = 0;
uint16_t buffer1_size;
uint16_t buffer2_size;
uint16_t buffer_size;
uint8_t filtered_msg_id_cnt = 0;

uint32_t update_size = 0;
uint32_t timer = 0;
uint32_t update_timer = 0;

bool buffer_full = false;
bool filtered_ids_recv  = false;
bool led_state = false;
bool wait = false;
bool update_available = false;

Adafruit_NeoPixel led(1, 13, NEO_GRB + NEO_KHZ800);

ESP32Time rtc;

void set_led_color(struct color c){
    led.setPixelColor(0, c.r * LED_BRIGHTNESS, c.g * LED_BRIGHTNESS, c.b * LED_BRIGHTNESS);
    led.show();
}

void blink(int tm, int d, struct color c){
    uint32_t start = millis();
    while (millis() - start < tm){
        set_led_color(c);
        delay(d);
        led.setPixelColor(0, 0);
        led.show();
        delay(d);
    }
}

int receive_update(uint32_t file_size){
    if (!Update.begin(file_size)){
        Serial.print(F("Failed to start update\r\n"));
        Update.printError(Serial);
        return -1;
    }
    Serial2.printf("{\"cmd\":\"start\",\"buff_size\":%d}\n", UPDATE_BUFFER_SIZE);
    Serial.print(F("start cmd sent\r\n"));
    uint8_t *update_buffer = (uint8_t*)malloc(UPDATE_BUFFER_SIZE);
    int received_size = 0;
    update_timer = millis();
    while (true){
        if (Serial2.available()){
            update_timer = millis();
            int size = (file_size - received_size >= UPDATE_BUFFER_SIZE) ? UPDATE_BUFFER_SIZE : (file_size % 1024);
            Serial.printf("Reading %d bytes\r\n", size);
            if (Serial2.readBytes(update_buffer, size) != size){
                Serial.print(F("receive Failed\r\n"));
                Update.abort();
                return -2;
            }
            if (Update.write(update_buffer, size) != size){
                Serial.print(F("Write Failed\r\n"));
                Update.printError(Serial);
                Update.abort();
                return -3;
            }
            toggle_led(cyan);
            received_size += size;
            Serial.printf("Updating %03d%%\r\n", (int)(((float)received_size / (float)file_size) * 100.0));
            Serial2.printf("ready\n");
            if (received_size == file_size){
                if (Update.end(true)){
                    Serial.print(F("Update Successfull\r\nRebooting...\r\n"));
                    Serial2.printf("done\n");
                    return 0;
                }
                else{
                    Serial.print(F("Update failed\r\n"));
                    Update.printError(Serial);
                    Update.abort();
                    return -4;
                }
            }
        }
        if (millis() - update_timer > 5000){
            Serial.print(F("update timedout!\r\n"));
            Update.abort();
            return -4;
        }
        delay(1);
    }
}

void setup() {
    Serial.begin(115200);
    Serial2.setRxBufferSize(UPDATE_BUFFER_SIZE * 2);
    Serial2.begin(921600, 134217756U, 14, 27);
    Serial2.onReceive(handle_serial_rx);
    led.begin();
    led.setBrightness(255);
    red.r = 255;
    green.g = 255;
    blue.b = 255;
    yellow.r = 255;
    yellow.g = 255;
    cyan.b = 255;
    cyan.g = 255;

    while (true){
        for (int i = 0; i < 10;i++){
            Serial.print(F("Requesting config...\r\n"));
            Serial2.printf("{\"cmd\":\"send_settings\"}\n");
            blink(3000, 100, yellow);
            if (filtered_ids_recv){
                Serial.print(F("Done\r\n"));
                break;
            }
            if (wait){
                i--;
                wait = false;
                Serial.print(F("Waiting for time set\r\n"));
            }
            else if (update_available){
                Serial2.onReceive(NULL);
                update_available = false;
                if (receive_update(update_size) == 0){
                    ESP.restart();
                }
                Serial2.onReceive(handle_serial_rx);
            }
            else{
                Serial.print(F("Failed\r\n"));
            }
        }
        if (filtered_ids_recv){
            break;
        }
        else{
            Serial.print(F("Failed 3 times, restarting wrover...\r\n"));
            restart_wrover();
            blink(10000, 100, yellow);
        }
    }

    Serial.printf("struct size = %u\r\n", sizeof(msg_t));

    // buffer1_size = ESP.getMaxAllocHeap() / sizeof(msg_t);
    buffer1_size = 5500;
    Serial.printf("free heap: %u - max alloc size: %u - buffer1 size: %u\r\n", ESP.getFreeHeap(), ESP.getMaxAllocHeap(), buffer1_size);
    buffer1 = (msg_t*)malloc(buffer1_size * sizeof(msg_t));

    // buffer2_size = ESP.getMaxAllocHeap() / sizeof(msg_t);
    buffer2_size = 5500;
    Serial.printf("free heap: %u - max alloc size: %u - buffer2 size: %u\r\n", ESP.getFreeHeap(), ESP.getMaxAllocHeap(), buffer2_size);
    buffer2 = (msg_t*)malloc(buffer2_size * sizeof(msg_t));

    buffer = buffer1;
    buffer_size = buffer1_size;

    CAN.setPins(18, 19);
    Serial.println(F("CAN Receiver"));
    // start the CAN bus at 125 kbps
    if (!CAN.begin(125E3)) {
        Serial.println(F("Starting CAN failed!"));
        while (1){
            blink(100000, 500, red);
        }
    }

    TaskHandle_t can_task;
    xTaskCreatePinnedToCore(can_loop, "can_loop", 1024, NULL, 1, &can_task, 0);
    set_led_color(green);
}

void restart_wrover(){

}

void handle_serial_rx(){
    DynamicJsonDocument doc(768);
    deserializeJson(doc, Serial2);
    serializeJson(doc, Serial);
    Serial.println();
    if (doc.containsKey("result")){
        if (strcmp(doc["result"].as<const char*>(), "ok") == 0){
            if (doc.containsKey("filter")){
                JsonArray ids = doc["filter"].as<JsonArray>();
                filtered_ids_recv = true;
                filtered_msg_id_cnt = ids.size();
                if (filtered_msg_ids != NULL){
                    free(filtered_msg_ids);
                    filtered_msg_ids = NULL;
                }
                if (filtered_msg_id_cnt != 0){
                    filtered_msg_ids = (uint32_t*)calloc(filtered_msg_id_cnt, 4);
                    for (int i = 0;i < filtered_msg_id_cnt; i++){
                        filtered_msg_ids[i] = ids[i].as<uint32_t>();
                    }
                }
                Serial.printf("Filtered msg ids:\r\n");
                for (int i = 0;i < filtered_msg_id_cnt; i++){
                    Serial.printf("%04X\r\n", filtered_msg_ids[i]);
                }
            }
            if (doc.containsKey("ts")){
                uint32_t ts = doc['ts'].as<uint32_t>();
                rtc.setTime(ts);
            }
        }
        else if (strcmp(doc["result"].as<const char*>(), "wait") == 0){
            wait = true;
        }
        else if (strcmp(doc["result"].as<const char*>(), "update") == 0){
            update_available = true;
            update_size = doc["size"].as<int>();
        }
    }
    doc.clear();
}

bool id_filtered(uint32_t id){
    for (int i = 0;i < filtered_msg_id_cnt;i++){
        if (filtered_msg_ids[i] == id){
            return true;
        }
    }
    return false;
}

void toggle_led(struct color c){
    if (led_state){
        set_led_color(c);
        led_state = false;
    }
    else{
        led.setPixelColor(0, 0);
        led.show();
        led_state = true;
    }
}

void can_loop(void *parameter){
    // timer = millis();
    while (true){
        // if (millis() - timer > 500){
        //     toggle_led(green);
        //     timer = millis();
        // }
        int packetSize = CAN.parsePacket();
        if (packetSize) {
            CAN.readBytes(buffer[buffer_index].d, 8);
            uint32_t packt_id = CAN.packetId();
            uint32_t mixed_id = (packt_id << 8) | buffer[buffer_index].d[7];
            // Serial.printf("mixed id: %06X\r\n", mixed_id);
            if (id_filtered(mixed_id)){
                // Serial.printf("ID %06X filtered\r\n", mixed_id);
                continue;
            }
            toggle_led(green);
            buffer[buffer_index].id = CAN.packetId();
            struct timeval tv;
            gettimeofday(&tv, NULL);
            buffer[buffer_index].ts = tv.tv_sec;
            buffer[buffer_index].us = tv.tv_usec;

            // Serial.printf("%lu -> %02X: %llu\r\n", micros(), CAN.packetId(), buffer[buffer_index].data);
            buffer_index++;
            if (buffer_index == buffer_size){
                if (buffer_full){
                    Serial.print(F("buffer overflow!\r\n"));
                    while (buffer_full){
                        vTaskDelay(10 / portTICK_PERIOD_MS);
                    }
                }
                buffer_index = 0;
                buffer = (buffer == buffer1 ? buffer2 : buffer1);
                buffer_size = (buffer_size == buffer1_size ? buffer2_size : buffer1_size);
                Serial.print(F("Buffer full, switch buffer\r\n"));
                buffer_full = true;
            }
        }
        vTaskDelay(1);
    }
}

void loop(){
    if (buffer_full){
        set_led_color(blue);
        // timer = millis();
        msg_t *temp_buffer = (buffer == buffer1 ? buffer2 : buffer1);
        uint16_t temp_buffer_size = (buffer == buffer1 ? buffer2_size : buffer1_size);
        Serial2.printf("{\"size\":%d}\n", temp_buffer_size * sizeof(msg_t));
        Serial2.write((char*)temp_buffer, temp_buffer_size * sizeof(msg_t));
        buffer_full = false;
    }
    vTaskDelay(100 / portTICK_PERIOD_MS);
}