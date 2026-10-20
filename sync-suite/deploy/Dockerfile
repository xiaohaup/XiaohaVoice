FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 XH_DATA_DIR=/data
RUN useradd --uid 10001 --create-home syncuser && mkdir /data && chown syncuser:syncuser /data
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY server /app/server
COPY web /app/web
USER 10001:10001
VOLUME /data
EXPOSE 8765
CMD ["uvicorn","server.app:create_app","--factory","--host","0.0.0.0","--port","8765","--workers","1","--no-access-log","--no-proxy-headers"]
