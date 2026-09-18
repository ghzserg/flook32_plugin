# Flook32

Author: @schreider
Fixes: @solitairweb

- (Flook32 Original Russian)[https://github.com/schreider/flook32]
- (Flook32 Translate English)[https://github.com/ghzserg/flook32]

1. Update plugin repo
   
   <img width="1046" height="422" alt="{EB2C300D-573D-46FF-87D4-0CDC3AB7DBE8}" src="https://github.com/user-attachments/assets/cac41d72-b0f2-4882-b3ba-0233fa011dfc" />
2. Recover Repo
   
   <img width="1005" height="198" alt="{10CBA32D-53AB-47C4-B723-0B253BDE56C9}" src="https://github.com/user-attachments/assets/62b0fd78-c498-4194-9ebc-2616b44e9162" />

3. Run the command: ```ENABLE_PLUGIN name=flook32```
   
   <img width="351" height="66" alt="{1D378E9A-6CBF-473C-9D89-ACEBB2E1EB33}" src="https://github.com/user-attachments/assets/9c1a480d-9765-4469-a4c6-b6668dffb72a" />

4. Add to `mod_data/user.cfg` flook32 values

Standard [flook32.cfg](https://github.com/ghzserg/flook32_plugin/blob/main/flook32.cfg) automated include

```
[temperature_sensor chamber]
sensor_type: flook32

#   sensor_type: flook32           # sensor type (required)
#   flook_ip: 192.168.1.37         # IP address (optional)
#   flook_port: 80                 # HTTP/WebSocket port
#   auto_discover: True            # auto-discovery via UDP (default True)
#   report_interval: 10.0          # ⚠️ HTTP MODE ONLY ⚠️
#                                  # HTTP polling interval (sec)
#                                  # Range: 5-60 sec, default 10 sec
#                                  # Does NOT affect WebSocket!
#   silent: False                  # Silent mode
#                                  # True  - do NOT output messages to console
#                                  # False - output all messages to console
...
```
# PS
This method describes connecting the plugin with default values, i.e., without control from Klipper, only displaying the chamber heating graph.

To add macros to the Fluidd interface, you need to copy `flook32.cfg` to `mod data` and uncomment the necessary lines.
```
# SLICER INTEGRATION (M141 / M191):                       
#   -----------------------------------------------------------------
#                                                                    
[gcode_macro M141]
gcode:
   {% set S = params.S|default(0)|float %}
   FLOOK_SET S={S}
                                                                    
[gcode_macro M191]
gcode:
   {% set S = params.S|default(0)|float %}
       FLOOK_SET S={S}
       {% if S > 0 %}
           TEMPERATURE_WAIT SENSOR="temperature_sensor chamber" MINIMUM={S-2} MAXIMUM={S+2}
       {% endif %}
```

In `mod_data/user.cfg` add the line

```
[include flook32.cfg]
```
