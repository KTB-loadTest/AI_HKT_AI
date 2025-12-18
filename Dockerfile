# =======================
# 1) Build stage
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

# 의존성만 먼저 복사하여 Docker 캐시 활용
COPY requirements.txt .

# 패키지들을 전역 사용자 공간에 설치 (멀티 스테이지에서 권장되는 패턴)
RUN pip install --user --no-cache-dir -r requirements.txt

# Playwright 브라우저 다운로드 (headless chromium만)
RUN ~/.local/bin/playwright install --with-deps chromium

# =======================
# 2) Runtime stage
# =======================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Runtime에도 Chromium 시스템 의존성 필요
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libdrm2 \
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

# uvicorn이 내부에서 0.0.0.0:8000으로 뜬다고 가정
EXPOSE 8000

WORKDIR /app

# builder 단계에서 설치한 패키지 복사
# /root/.local/ 이 --user 설치 기본 경로
# 브라우저 복사
COPY --from=builder /root/.local /root/.local
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# PATH에 user base bin 추가
ENV PATH=/root/.local/bin:${PATH}

# 앱 소스 복사
COPY . .

# 브라우저 실행 권한 확인
RUN chmod -R +x /root/.cache/ms-playwright

# uvicorn으로 FastAPI 실행
# app/main.py 안에 "app = FastAPI()" 가 있다고 가정
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
