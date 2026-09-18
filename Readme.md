#Flook32

https://github.com/schreider/flook32

1. Add to `umod_data/ser.moonraker.conf`

```
[update_manager flook32]
type: git_repo
channel: stable
path: /root/printer_data/config/mod_data/plugins/flook32
origin: https://github.com/ghzserg/flook32_plugin.git
is_system_service: False
primary_branch: main
```

2. Reboot printer
3. Run the command: ```ENABLE_PLUGIN name=flook32```
4. Add to `mod_data/user.cfg` flook32 values

```
[temperature_sensor chamber]
sensor_type: flook32

#   sensor_type: flook32           # тип датчика (обязательно)
#   flook_ip: 192.168.1.37         # IP адрес (опционально)
#   flook_port: 80                 # порт HTTP/WebSocket
#   auto_discover: True            # авто-поиск по UDP (по умолч. True)
#   report_interval: 10.0          # ⚠️ ТОЛЬКО ДЛЯ HTTP РЕЖИМА ⚠️
#                                  # Интервал опроса через HTTP (сек)
#                                  # Диапазон: 5-60 сек, по умолч. 10 сек
#                                  # НЕ влияет на WebSocket!
#   silent: False                  # Тихий режим
#                                  # True  - НЕ выводить сообщения в консоль
#                                  # False - выводить все сообщения в консоль
...
```

@schreider @solitairweb
