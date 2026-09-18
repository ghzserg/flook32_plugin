# Flook32

Author: @schreider
Fixes: @solitairweb

https://github.com/schreider/flook32

1. Add to `mod_data/user.moonraker.conf`

```
[update_manager flook32]
type: git_repo
channel: stable
path: /root/printer_data/config/mod_data/plugins/flook32
origin: https://github.com/ghzserg/flook32_plugin.git
is_system_service: False
primary_branch: main
```
<img width="738" height="302" alt="{235DF6B8-2181-4C61-B8BD-48ABEDE8E224}" src="https://github.com/user-attachments/assets/adc47634-1232-4ffa-896e-027f15ab10a9" />

2. Reboot printer
3. Update plugin repo
   
   <img width="1046" height="422" alt="{EB2C300D-573D-46FF-87D4-0CDC3AB7DBE8}" src="https://github.com/user-attachments/assets/cac41d72-b0f2-4882-b3ba-0233fa011dfc" />
5. Recover Repo
   
   <img width="1005" height="198" alt="{10CBA32D-53AB-47C4-B723-0B253BDE56C9}" src="https://github.com/user-attachments/assets/62b0fd78-c498-4194-9ebc-2616b44e9162" />

7. Run the command: ```ENABLE_PLUGIN name=flook32```
   
   <img width="351" height="66" alt="{1D378E9A-6CBF-473C-9D89-ACEBB2E1EB33}" src="https://github.com/user-attachments/assets/9c1a480d-9765-4469-a4c6-b6668dffb72a" />

9. Add to `mod_data/user.cfg` flook32 values

Standart [flook32.cfg](https://github.com/ghzserg/flook32_plugin/blob/main/flook32.cfg) automated include

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
