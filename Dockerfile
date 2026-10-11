FROM python:3.12-slim
WORKDIR /app
COPY selcal.py server.py index.html ./
ENV HOST=0.0.0.0 PORT=8787 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
EXPOSE 8787
CMD ["python", "server.py"]
