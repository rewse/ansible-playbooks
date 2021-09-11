FROM homeassistant/raspberrypi4-homeassistant:stable

RUN apk add --update patch
RUN pip3 install --upgrade pip
RUN pip3 install pysesame3==0.4.1

COPY sensor.patch /tmp/
RUN patch /usr/src/homeassistant/homeassistant/components/imap_email_content/sensor.py /tmp/sensor.patch
