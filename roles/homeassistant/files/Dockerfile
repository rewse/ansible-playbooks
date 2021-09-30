FROM homeassistant/raspberrypi4-homeassistant:stable

RUN apk add --update patch

COPY sensor.patch /tmp/
RUN patch /usr/src/homeassistant/homeassistant/components/imap_email_content/sensor.py /tmp/sensor.patch
