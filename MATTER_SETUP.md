# Lumi Matter Bridge - Setup Guide

## Что это?

Это Matter Bridge для Xiaomi Lumi Gateway, который позволяет подключить ваш шлюз к Яндекс Станции через протокол Matter.

## Поддерживаемые устройства

- ✅ RGB LED подсветка (управление цветом, яркостью)
- ✅ Кнопка с событиями (single, double, triple, hold, release)

## Установка

### 1. Установите зависимости

```bash
pip3 install -r requirements.txt
```

Или на OpenWrt:

```bash
opkg update
opkg install python3-pip python3-asyncio python3-evdev
pip3 install zeroconf qrcode colorama cryptography
```

### 2. Создайте конфигурационный файл

Скопируйте `lumimqtt.json` в `/etc/lumimqtt.json` или используйте переменную окружения:

```json
{
  "device_id": "lumi_gateway_001",
  "device_name": "Lumi Gateway",
  
  "matter": {
    "vendor_id": 65521,
    "product_id": 32769,
    "discriminator": 3840,
    "passcode": 20202021
  },
  
  "binary_sensors": {},
  "custom_commands": {}
}
```

### 3. Запустите Matter Bridge

```bash
# С конфигом по умолчанию (/etc/lumimqtt.json)
python3 -m lumimqtt

# Или с кастомным конфигом
LUMIMQTT_CONFIG=./lumimqtt.json python3 -m lumimqtt
```

## Что произойдёт при запуске

При запуске вы увидите в консоли:

```
============================================================
🔗 MATTER DEVICE PAIRING INFORMATION
============================================================
Device Name: Lumi Gateway
Device ID: lumi_gateway_001
Vendor ID: 0xFFF1
Product ID: 0x8001
------------------------------------------------------------
📱 Manual Pairing Code: 38400-2020202
🔢 Discriminator: 3840
🔐 Setup PIN: 20202021
------------------------------------------------------------
📷 QR Code - scan with Yandex Station:

[ASCII QR КОД]

============================================================
ℹ️  Instructions:
1. Open Yandex Station app
2. Go to 'Add Device' -> 'Matter'
3. Scan QR code above OR enter manual code
4. Follow on-screen instructions
============================================================
```

## Подключение к Яндекс Станции

### Способ 1: Сканирование QR кода

1. Откройте приложение Яндекс (с управлением Яндекс Станцией)
2. Перейдите в раздел "Устройства" → "Добавить устройство"
3. Выберите "Matter устройство"
4. Отсканируйте QR код из консоли

### Способ 2: Ручной ввод кода

1. Откройте приложение Яндекс
2. Перейдите в раздел "Устройства" → "Добавить устройство"
3. Выберите "Matter устройство" → "Ввести код вручную"
4. Введите код из консоли (например: `38400-2020202`)

## Управление устройствами

После подключения в Яндекс Станции вы увидите:

- **RGB Лампа** - можно управлять:
  - Включение/выключение
  - Яркость (0-100%)
  - Цвет (RGB)
  - Говорить: "Алиса, включи свет", "Алиса, сделай свет красным"

- **Кнопка** - генерирует события:
  - Одно нажатие
  - Двойное нажатие
  - Длительное удержание
  - Можно использовать в сценариях Яндекс

## Автозапуск на OpenWrt

Создайте init скрипт `/etc/init.d/lumimatter`:

```bash
#!/bin/sh /etc/rc.common

START=99
STOP=10

USE_PROCD=1
PROG=/usr/bin/python3

start_service() {
    procd_open_instance
    procd_set_param command $PROG -m lumimqtt
    procd_set_param env LUMIMQTT_CONFIG=/etc/lumimqtt.json
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
```

Включите автозапуск:

```bash
chmod +x /etc/init.d/lumimatter
/etc/init.d/lumimatter enable
/etc/init.d/lumimatter start
```

## Отладка

Для отладки включите подробное логирование:

```python
# В __main__.py измените уровень логирования
logging.basicConfig(level=logging.DEBUG)
```

## Примечания

- Matter использует mDNS для обнаружения устройств в локальной сети
- Убедитесь, что Яндекс Станция и шлюз находятся в одной сети
- Порт 5540/UDP должен быть открыт для Matter коммуникации
- После первого сопряжения QR код больше не показывается (устройство уже в сети Matter)

## Технические детали

- **Протокол**: Matter 1.0+
- **Транспорт**: UDP/IP (локальная сеть)
- **Обнаружение**: mDNS (Bonjour/Avahi)
- **Тип устройства RGB LED**: Extended Color Light (0x010D)
- **Тип устройства кнопки**: Generic Switch (0x000F)

## Поддержка

Если возникли проблемы:
1. Проверьте, что все зависимости установлены
2. Убедитесь, что устройства (LED, кнопка) доступны в системе
3. Проверьте логи: `journalctl -u lumimatter -f`
