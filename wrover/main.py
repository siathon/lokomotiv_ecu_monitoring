import os
import machine
from time import time_ns, localtime, sleep_ms, time, mktime, ticks_ms
from sys import print_exception
import _thread
import json
import gc
import network
import ntptime
import socket
from micropyGPS import MicropyGPS
from neopixel import NeoPixel
import select

ntptime.host = '45.147.77.196'

Red='\033[0;31m'
Green='\033[0;32m'
Yellow='\033[0;33m'
Magenta='\033[0;35m'
Cyan='\033[0;36m'
White='\033[0;37m'

red    = (255,   0,   0)
green  = (  0, 255,   0)
blue   = (  0,   0, 255)
yellow = (255, 255,   0)
purple = (255,   0, 255)
off    = (  0,   0,   0)
white  = (255, 255, 255)

LED_BRIGHTNESS = 0.3

# led = NeoPixel(machine.Pin(32, machine.Pin.OUT), 1)

def set_led_color(c):
    led[0] = (int(c[0] * LED_BRIGHTNESS), int(c[1] * LED_BRIGHTNESS), int(c[2] * LED_BRIGHTNESS))
    led.write()

def print_colored(text, color=Yellow):
    print(f'{color}{text}{White}')

set_led_color(yellow)
lan = network.LAN(mdc=machine.Pin(23), mdio=machine.Pin(18), power=machine.Pin(5), id=None, phy_addr=0, phy_type=network.PHY_LAN8720)

try:
    lan.active(True)
except:
    lan.active(False)
    lan.active(True)

# sd = machine.SDCard(slot=3, mosi=13, miso=39, sck=14, cs=4, freq=20000000)

can_uart = machine.UART(1, baudrate=921600, rx=2, tx=15, timeout=1500, rxbuf=120100)
gps_uart = machine.UART(2, baudrate=9600, rx=34, tx=33)
gps = MicropyGPS(location_formatting='dd')
rtc = machine.RTC()
wdt = machine.WDT(timeout=10000)


class App:
    def __init__(self):
        self.prev_filename = ''
        self.curr_filename = ''
        self.sd_lock = _thread.allocate_lock()
        self.tm = 0
        self.lan_tm = 0
        self.data_blk_size = 20480
        self.config = {}
        self.time_set = False
        self.led_state = False
        self.gps_time_set = False
        self.wroom_update_available = False
        self.watchdog_timer = 0

    def init_sd(self):
        try:
            print_colored("Initializing SD card")
            sz, blk_sz = sd.info()
            print_colored(f'sd card size: {sz / 1024 / 1024 / 1024}GiB')
            ls = os.listdir('/')
            if 'sd' in ls:
                os.umount('/sd')
            os.mount(sd, '/sd')
            ls = os.listdir('/sd')
            if 'wroom.ino.bin' in ls:
                self.wroom_update_available = True
            if 'files_to_send' not in ls:
                os.mkdir('/sd/files_to_send')
            if 'data' not in ls:
                os.mkdir('/sd/data')
            else:
                ls = os.listdir('/sd/data')
                for file in ls:
                    sz = os.stat(f'/sd/data/{file}')[6]
                    if sz > 0:
                        print(f'creating file /sd/files_to_send/{file}')
                        with open(f'/sd/files_to_send/{file}', 'w') as f:
                            pass
                        print('Done')
                    else:
                        os.remove(f'/sd/files_to_send/{file}')
                    wdt.feed()
                        
            print_colored("Done")
            return True
        except Exception as e:
#             print_exception(e)
            print_colored("Failed to mount SD card")
            return False
    
    def now(self):
        return time() + 946684800
    
    def now_tz(self):
        return localtime(time() + self.config['time_offset'])
    
    def check_config(self):
        if 'filter' not in self.config:
            self.config['filter'] = []
        else:
            self.config['filter'] = list(map(int, self.config['filter'], [16] * len(self.config['filter'])))

        if 'time_offset' not in self.config:
            self.config['time_offset'] = 0
        
    
    def load_config(self):
        print_colored("Loading config")
        ls = os.listdir('/sd')
        if 'config.json' in ls:
            try:
                with open('/sd/config.json') as f:
                    self.config = json.load(f)
                print_colored("Done")
                print_colored(json.dumps(self.config))
            except Exception as e:
                print_colored('Failed to load config file')
                print_exception(e)
        else:
            print_colored('config file not found')
    
    def check_file_name(self):
        self.prev_filename = self.curr_filename
        tm = self.now_tz()
        self.curr_filename = f'{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d}_{tm[3]:02d}-{tm[4]:02d}'
        if self.prev_filename and self.prev_filename != self.curr_filename:
            try:
                self.sd_lock.acquire()
                print(f'creating location file /sd/data/{self.prev_filename}.loc')
                with open(f'/sd/data/{self.prev_filename}.loc', 'w') as f:
                    gps_lat = gps.latitude
                    gps_lon = gps.longitude
                    loc = {'lat': gps_lat[0] * (-1 if gps_lat[1] == 'S' else 1),
                           'lon': gps_lon[0] * (-1 if gps_lon[1] == 'W' else 1),
                           'alt': gps.altitude, 'spd': gps.speed[2]}
                    json.dump(loc, f)
                print('Done')
                
                print(f'creating file /sd/files_to_send/{self.prev_filename}.loc')
                with open(f'/sd/files_to_send/{self.prev_filename}.loc', 'w') as f:
                    pass
                print('Done')
            except Exception as e:
                print_exception(e)
            
            try:
                ls = os.listdir('/sd/data')
                if f'{self.prev_filename}.bin' in ls:
                    sz = os.stat(f'/sd/data/{self.prev_filename}.bin')[6]
                    if sz > 0:
                        print(f'creating file /sd/files_to_send/{self.prev_filename}.bin')
                        with open(f'/sd/files_to_send/{self.prev_filename}.bin', 'w') as f:
                            pass
                        print('Done')
                    else:
                        os.remove(f'/sd/files_to_send/{self.prev_filename}.bin')
            except Exception as e:
                print_exception(e)
            
            if self.sd_lock.locked():
                self.sd_lock.release()
    def write_buffer_to_sd(self, data):
        try:
            success = False
            for i in range(3):
                print(f'Writting buffer to /sd/data/{self.curr_filename}.bin...')
                self.sd_lock.acquire()
                f = None
                try:
                    f = open(f'/sd/data/{self.curr_filename}.bin', 'ab')
                    f.write(data)
                    f.close()
                    success = True
                    self.sd_lock.release()
                    break
                except:
                    print("Failed")
                    if f:
                        f.close()
                    if self.sd_lock.locked():
                        self.sd_lock.release()
            if success:
                print("Done")
            else:
                print("Failed to write data")
                
        except Exception as e:
            print_exception(e)
        finally:
            if self.sd_lock.locked():
                self.sd_lock.release()
            
    def net_loop(self):
        file = None
        while True:
            try:
                if not self.time_set and not self.gps_time_set:
                    date = gps.date
                    if date[0] != 0:
                        time = gps.timestamp
                        tm=localtime(mktime((date[0], date[1], date[2],
                                      time[0], time[1], int(time[2]), 0, 0)))
                        rtc.datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
                        self.gps_time_set = True
                        
                if lan.isconnected():
                    if not self.time_set:
                        try:
                            ntptime.settime()
                            self.time_set = True
                        except:
                            pass

#                     print_colored('checking files ready to send', Cyan)
                    self.sd_lock.acquire()
                    try:
                        ls = os.listdir('/sd/files_to_send')
                    except:
                        print("Failed to get file list", Cyan)
                        self.sd_lock.release()
                        sleep_ms(100)
                        continue
                    
                    self.sd_lock.release()
#                     print_colored(f'{len(ls)} files ready to send', Cyan)
                    for f in ls:
                        self.sd_lock.acquire()
                        try:
                            sz = os.stat(f'/sd/data/{f}')[6]
                        except:
                            print_colored("Failed to get file size", Cyan)
                            self.sd_lock.release()
                            break
                        
                        self.sd_lock.release()
                        block_cnt = sz // self.data_blk_size + (0 if (sz % self.data_blk_size == 0) else 1)
                        print_colored(f'sending {f} with size {sz} in {block_cnt} blocks', Cyan)
                        
                        print_colored(f'opening file {f}', Cyan)
                        self.sd_lock.acquire()
                        try:
                            file = open(f'/sd/data/{f}', 'rb')
                        except:
                            print_colored('failed to open file')
                            self.sd_lock.release()
                            continue
                        
                        self.sd_lock.release()
                        print_colored('Done', Cyan)
                        s = socket.socket()
                        s.settimeout(3)    
                        print_colored('Connecting to server...', Cyan)
                        self.watchdog_timer = ticks_ms()
                        try:
                            s.connect(('217.172.121.89', 5000))
                            s.setblocking(False)
                        except:
                            print_colored("Failed", Cyan)
                            self.sd_lock.acquire()
                            file.close()
                            self.sd_lock.release()
                            s.close()
                            sleep_ms(1000)
                            break
                            
                        print_colored('Done', Cyan)
                        s.send(json.dumps({'filename':f}).encode())
                        send_start = time_ns() // 1000000
                        success = False
                        print_colored('Sending data...', Cyan)
                        
                        for b in range(block_cnt):
                            self.blink(purple)
#                             print_colored(f'reading block {b+1}', Cyan)
                            read_start = time_ns() // 1000000
                            self.sd_lock.acquire()
                            for i in range(3):
                                try:
                                    blk_sz = sz % self.data_blk_size if (b + 1 == block_cnt and sz % self.data_blk_size != 0) else (self.data_blk_size)
                                    data = file.read(blk_sz)
                                    if len(data) != blk_sz:
                                        print(f'blk size = {blk_sz} data size = {len(data)}')
                                        raise OSError
                                    success = True
                                    break
                                except:
                                    print_colored('Failed', Cyan)
                                    success = False
                                    self.watchdog_timer = ticks_ms()
                            
                            self.sd_lock.release()        
                            if not success:
                                break
#                             print_colored(f'read time {time_ns() // 1000000 - read_start}', Cyan)
                            while len(data):
                                success = False
                                try:
                                    sent = s.write(data)
                                    poller = select.poll()
                                    poller.register(s, select.POLLOUT)
                                    res = poller.poll(3000)
                                    if not res:
                                        raise OSError
                                    data = data[sent:]
                                    success = True
                                    self.watchdog_timer = ticks_ms()
                                except:
                                    break
                            self.watchdog_timer = ticks_ms()
                            if not success:
                                break
#                             sleep_ms(1)
                        self.watchdog_timer = ticks_ms()
                        self.sd_lock.acquire()
                        file.close()
                        self.sd_lock.release()
                        s.close()
                        if success:
                            print_colored('Done', Cyan)
                            print_colored(f'upload time: {time_ns() // 1000000 - send_start}', Cyan)
                            self.sd_lock.acquire()
                            os.remove(f'/sd/files_to_send/{f}')
                            os.remove(f'/sd/data/{f}')
                            self.sd_lock.release()
                        else:
                            print_colored("Failed to send data", Cyan)
                            break
                self.watchdog_timer = ticks_ms()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print_exception(e)
            finally:
                if self.sd_lock.locked():
                    self.sd_lock.release()
                if file:
                    self.sd_lock.acquire()
                    file.close()
                    file = None
                    self.sd_lock.release()
            self.watchdog_timer = ticks_ms()
            sleep_ms(100)
    
    def send_update(self):
        file_size = os.stat(f'/sd/wroom.ino.bin')[6]
        can_uart.write(json.dumps({'result':'update', 'size':file_size}))
        start = ticks_ms()
        while True:
            if can_uart.any():
                cmd = can_uart.readline()
                print(cmd)
                try:
                    cmd = json.loads(cmd)
                except:
                    continue
                
                if 'cmd' in cmd and cmd['cmd'] == 'start':
                    break
                
            sleep_ms(100)
            self.blink(white)
            wdt.feed()
            if ticks_ms() - start > 5000:
                return
        
        wdt.feed()
        f = open('/sd/wroom.ino.bin', 'rb')
        block_cnt = file_size // cmd['buff_size'] + (0 if file_size % cmd['buff_size'] == 0 else 1)
        for b in range(block_cnt):
            self.blink(white)
            blk_size = file_size % cmd['buff_size'] if (b + 1 == block_cnt and file_size % cmd['buff_size'] != 0) else (cmd['buff_size'])
            print(f'Sending block {b} size: {blk_size}')
            can_uart.write(f.read(blk_size))
            if can_uart.readline().decode() != 'ready\n':
                return
            wdt.feed()
        f.close()
        self.wroom_update_available = False
        os.remove('/sd/wroom.ino.bin')
            
    def send_settings(self):
        if self.wroom_update_available:
            self.send_update()
        elif self.time_set or self.gps_time_set:
            can_uart.write(json.dumps({'result':'ok', 'filter':self.config['filter'], 'ts':self.now()}))
        else:
            can_uart.write(json.dumps({'result':'wait'}))
    
    def handle_gps(self):
        while True:
            while(gps_uart.any()):
                try:
                    gps.update(gps_uart.read(1).decode())
                    sleep_ms(1)
                except Exception as e:
                    pass
#                     print_colored(f'{e}', Red)
            sleep_ms(700)
            
    def blink(self, c):
        if self.led_state:
            self.led_state = False
            set_led_color(off)
        else:
            self.led_state = True
            set_led_color(c)
                
    def main_loop(self):
        print("Main loop started")
        can_uart.flush()
        while True:
            self.blink(green)
            if self.time_set or self.gps_time_set:
                self.check_file_name()
            if can_uart.any():
                l = can_uart.readline()
                try:
                    data = json.loads(l)
                    if 'cmd' in data:
                        if data['cmd'] == 'send_settings':
                            print_colored("setting request received")
                            self.send_settings()
                            continue
                except Exception as e:
#                     print_exception(e)
                    continue
                if 'size' not in data:
                    continue
                set_led_color(blue)
                size = data['size']
                self.tm = time_ns() // 1000000
                data = can_uart.read(size)
                print(size, len(data))
                if size == len(data):
                    self.write_buffer_to_sd(data)
                else:
                    print('corrupted data')
                del data
                gc.collect()
            if ticks_ms() - self.watchdog_timer < 5000:
                wdt.feed()
            sleep_ms(500)

wdt.feed()
app = App()
if not app.init_sd():
    while True:
        set_led_color(red)
        sleep_ms(500)
        set_led_color(off)
        sleep_ms(500)
wdt.feed()
app.load_config()
app.check_config()
_thread.start_new_thread(app.handle_gps, ())
sleep_ms(100)
_thread.start_new_thread(app.net_loop, ())
sleep_ms(100)
wdt.feed()
app.main_loop()
