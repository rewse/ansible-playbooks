FROM ghcr.io/home-assistant/home-assistant:stable

RUN apk add --update patch

COPY sensor.patch /tmp/
RUN patch /usr/src/homeassistant/homeassistant/components/imap_email_content/sensor.py /tmp/sensor.patch
