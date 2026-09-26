# 运行时基础镜像固定为 Python 3.12
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 只拷贝服务代码；测试与文档不进运行时镜像
COPY app ./app

# 以非 root 用户运行
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# 单命令拉起服务；多核环境可加 --workers N 水平扩展（引擎无状态，天然安全）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
