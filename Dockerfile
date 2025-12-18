# =======================
# 1) Builder stage
# =======================
FROM python:3.11-slim AS builder

# Playwright Chromium 실행에 필요한 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Playwright 브라우저 다운로드
RUN ~/.local/bin/playwright install chromium

# =======================
# 2) Runtime stage
# =======================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Runtime에 필요한 의존성 (libgbm1 추가)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

WORKDIR /app

# Builder에서 설치한 패키지와 Playwright 브라우저 복사
COPY --from=builder /root/.local /root/.local
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# PATH에 user base bin 추가
ENV PATH=/root/.local/bin:${PATH}

# 앱 소스 복사
COPY . .

# 브라우저 실행 권한 확인
RUN chmod -R +x /root/.cache/ms-playwright

# uvicorn으로 FastAPI 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
