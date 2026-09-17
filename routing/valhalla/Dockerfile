FROM ghcr.io/interline-io/valhalla-docker/valhalla:latest

COPY start-valhalla.sh /usr/local/bin/start-valhalla.sh
RUN chmod +x /usr/local/bin/start-valhalla.sh

EXPOSE 8002
ENTRYPOINT ["/usr/local/bin/start-valhalla.sh"]
