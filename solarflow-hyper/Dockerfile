ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:3.20
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip && \
    pip3 install paho-mqtt --break-system-packages

COPY rootfs /
RUN chmod a+x /usr/bin/solarflow-hyper.py \
              /etc/services.d/solarflow-hyper/run
