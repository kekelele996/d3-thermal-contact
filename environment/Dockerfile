FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 解题与参考解的身份由 task.toml 的 [agent] user = "runner" 指定。
# 容器默认用户保持 root：Harbor 的保活进程随默认用户运行，评分前清理 runner
# 进程时不能把它一起结束。
RUN useradd --create-home --uid 1000 runner

RUN pip install --no-cache-dir numpy==2.1.3 scipy==1.14.1

WORKDIR /app
COPY app/ /app/
RUN chown -R runner:runner /app
