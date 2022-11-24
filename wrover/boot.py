import os
import machine
from sys import print_exception
from neopixel import NeoPixel
from time import sleep_ms

led = NeoPixel(machine.Pin(32, machine.Pin.OUT), 1)
sd = machine.SDCard(slot=3, mosi=13, miso=39, sck=14, cs=4, freq=20000000)

led_state = False
LED_BRIGHTNESS = 0.1
off  = (  0,   0,   0)
cyan = (  0, 255, 255)

def set_led_color(c):
    led[0] = (int(c[0] * LED_BRIGHTNESS), int(c[1] * LED_BRIGHTNESS), int(c[2] * LED_BRIGHTNESS))
    led.write()

def blink(c):
    global led_state
    if led_state:
        led_state = False
        set_led_color(off)
    else:
        led_state = True
        set_led_color(c)

try:
    os.mount(sd, '/sd')
    ls = os.listdir('/sd')
    if 'main.py' in ls:
        print('update found on sd')
        if 'main.py' in os.listdir('/'):
            print('removed main.py from flash')
            os.remove('/main.py')
        print('copying main.py from sd to main.py on flash')
        file_size = os.stat('/sd/main.py')[6]

        with open('/sd/main.py', 'rb') as f:
            with open('/main.py', 'wb') as g:
                while g.write(f.read(1024)) == 1024:
                    blink(cyan)
        os.remove('/sd/main.py')
        print('done')
        while True:
            blink(cyan)
            sleep_ms(500)
except Exception as e:
    print("sd not found")
    print_exception(e)

ls = os.listdir('/')
if 'sd' in ls:
    os.umount('/sd')
