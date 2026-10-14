ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip && \
    pip3 install paho-mqtt==2.1.0 --break-system-packages

COPY rootfs /
RUN chmod a+x /usr/bin/solarflow-hyper.py \
              /etc/services.d/solarflow-hyper/run
