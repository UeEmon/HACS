FROM python:3.12-slim
WORKDIR /app
COPY selcal.py tail_mapping.py server.py index.html receiver.py receiver_server.py receiver.html ./
ENV HOST=0.0.0.0 PORT=8787 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
EXPOSE 8787 8788
CMD ["python", "server.py"]
