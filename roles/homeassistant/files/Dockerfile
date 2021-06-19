FROM homeassistant/raspberrypi4-homeassistant:stable

RUN apk add --update patch
RUN pip3 install pysesame3

COPY homeassistant/sensor.patch /tmp/
RUN patch /usr/src/homeassistant/homeassistant/components/imap_email_content/sensor.py /tmp/sensor.py
