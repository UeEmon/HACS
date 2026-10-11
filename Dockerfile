FROM python:3.12-slim
WORKDIR /app
LABEL org.opencontainers.image.licenses="Apache-2.0"
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./
COPY selcal.py tail_mapping.py key_store.py key_admin.py wav_context.py rotation.py rotation_ui.js presets.py preset_exports.py presets_ui.js keys_ui.js loopback_ui.js server.py index.html receiver.py receiver_server.py receiver.html ./
RUN mkdir -p /data /keydata && chown 65534:65534 /data /keydata && chmod 700 /keydata
ENV HOST=0.0.0.0 PORT=8787 PYTHONDONTWRITEBYTECODE=1 HACS_DATA_DIR=/data
USER 65534:65534
EXPOSE 8787 8788
CMD ["python", "server.py"]
