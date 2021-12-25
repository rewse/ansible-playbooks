FROM homeassistant/raspberrypi4-homeassistant:stable

RUN apk add --update patch

COPY sensor.patch /tmp/
RUN patch /usr/src/homeassistant/homeassistant/components/imap_email_content/sensor.py /tmp/sensor.patch

COPY openapi.py.patch /tmp/
RUN patch /usr/local/lib/python3.9/site-packages/tuya_iot/openapi.py /tmp/openapi.py.patch
