#!/bin/sh
#!/bin/sh

[ -f /usr/data/zmod/zmod/.shell/0.sh ] && source /usr/data/zmod/zmod/.shell/0.sh

if [ -f /ZMOD ]; then
    /usr/data/zmod/zmod/.shell/zremote.sh /opt/config/mod_data/plugins/flook32/update.sh
    exit 0
fi

rm -f /usr/data/zmod/klipper/klippy/extras/flook32.py /usr/prog/klipper/klippy/extras/flook32.py

echo "flook32 uninstalled"
